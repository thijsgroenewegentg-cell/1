# /modules/models.py
"""Manage the local Ollama models JARVIS runs on, from inside the conversation.

Swapping brains normally means editing ``config.yaml`` and restarting. This
module lets you ask instead: "what models do I have", "pull qwen2.5", "switch
to mistral", "which model should I use for coding". Everything talks to the
local Ollama HTTP API — no account, no key, no cloud.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, ClassVar, Dict, List, Optional, Tuple

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.helpers import human_bytes, human_duration, truncate

#: Curated free models worth suggesting, with rough download sizes and the
#: amount of RAM you want free to run them comfortably.
CATALOG: Tuple[Dict[str, Any], ...] = (
    {"name": "llama3.2:3b", "size_gb": 2.0, "ram_gb": 8,
     "good_at": "general chat, fast replies, weak laptops", "tags": ("general", "fast")},
    {"name": "llama3.1:8b", "size_gb": 4.7, "ram_gb": 16,
     "good_at": "general reasoning, longer answers", "tags": ("general", "reasoning")},
    {"name": "mistral:7b", "size_gb": 4.1, "ram_gb": 16,
     "good_at": "concise general use, tool calling", "tags": ("general", "tools")},
    {"name": "qwen2.5:7b", "size_gb": 4.7, "ram_gb": 16,
     "good_at": "reasoning, maths, multilingual", "tags": ("reasoning", "maths",
                                                           "multilingual")},
    {"name": "qwen2.5-coder:7b", "size_gb": 4.7, "ram_gb": 16,
     "good_at": "writing and debugging code", "tags": ("code",)},
    {"name": "deepseek-coder-v2:16b", "size_gb": 8.9, "ram_gb": 32,
     "good_at": "serious coding work", "tags": ("code",)},
    {"name": "phi3:mini", "size_gb": 2.2, "ram_gb": 8,
     "good_at": "very fast routing and classification", "tags": ("fast", "router")},
    {"name": "gemma2:9b", "size_gb": 5.4, "ram_gb": 16,
     "good_at": "well-rounded writing", "tags": ("general", "writing")},
    {"name": "llava:7b", "size_gb": 4.7, "ram_gb": 16,
     "good_at": "looking at screenshots and images", "tags": ("vision",)},
    {"name": "nomic-embed-text", "size_gb": 0.3, "ram_gb": 4,
     "good_at": "embeddings for memory and document search", "tags": ("embedding",)},
)

#: Which catalogue tag matches which kind of request.
PURPOSE_TAGS: Dict[str, str] = {
    "code": "code", "coding": "code", "programming": "code", "python": "code",
    "fast": "fast", "quick": "fast", "speed": "fast", "small": "fast", "laptop": "fast",
    "reasoning": "reasoning", "maths": "maths", "math": "maths", "logic": "reasoning",
    "vision": "vision", "image": "vision", "screenshot": "vision", "see": "vision",
    "translation": "multilingual", "multilingual": "multilingual", "language": "multilingual",
    "writing": "writing", "write": "writing", "essay": "writing",
    "embedding": "embedding", "memory": "embedding", "search": "embedding",
    "router": "router", "routing": "router",
}


class Models(BaseModule):
    """Inspect, download, switch and remove local Ollama models."""

    name = "models"
    description = (
        "Manage the local LLMs JARVIS runs on: list installed models, download new "
        "ones, switch the active model, remove models to free disk space, and "
        "recommend which free model suits a task. Use for anything about models, "
        "Ollama, download sizes or how fast/slow JARVIS is."
    )
    intent_examples: ClassVar[List[str]] = [
        "what models do i have",
        "switch to mistral",
        "download qwen2.5",
        "which model is best for coding",
        "how much disk are my models using",
        "delete llama2 to free up space",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Record where Ollama lives and how long downloads may take."""
        super().__init__(config, llm=llm, security=security)
        self.host: str = str(config.get("llm.host", "http://localhost:11434")).rstrip("/")
        self.pull_timeout: float = float(config.get("llm.pull_timeout", 3600))
        self.brain: Any = None
        self._pulling: Optional[str] = None

    # ------------------------------------------------------------------ infra
    async def _client(self) -> Any:
        """Return an ``httpx.AsyncClient``, or ``None`` when httpx is missing."""
        try:
            import httpx
        except Exception as exc:  # pragma: no cover - httpx is a hard dependency
            self.log.error("httpx unavailable: %s", exc)
            return None
        return httpx.AsyncClient(timeout=30.0)

    async def _tags(self) -> Optional[List[Dict[str, Any]]]:
        """Fetch the raw ``/api/tags`` payload, or ``None`` when Ollama is down."""
        client = await self._client()
        if client is None:
            return None
        try:
            response = await client.get(f"{self.host}/api/tags")
            response.raise_for_status()
            payload = response.json()
            models = payload.get("models", [])
            return [entry for entry in models if isinstance(entry, dict)]
        except Exception as exc:
            self.log.debug("Could not list models: %s", exc)
            return None
        finally:
            await client.aclose()

    @staticmethod
    def _offline() -> ModuleResult:
        """The standard answer when the Ollama server is not answering."""
        return ModuleResult.fail(
            "Ollama isn't answering, sir. Start it with 'ollama serve' and try again."
        )

    def _active_model(self) -> str:
        """The model the brain is currently generating with."""
        return str(getattr(self.llm, "model", "") or self.config.get("llm.model", ""))

    # ------------------------------------------------------------------ tools
    @tool(
        description="List the local models, their size on disk, and which one is active.",
        params={},
        keywords=["what models", "list models", "which models", "models do i have",
                  "installed models", "my models", "model list", "how much disk are my models"],
        examples=["list_models()"],
    )
    async def list_models(self) -> ModuleResult:
        """Show every installed Ollama model.

        Returns:
            A table of models with sizes, plus the active one.
        """
        entries = await self._tags()
        if entries is None:
            return self._offline()
        if not entries:
            return ModuleResult.ok(
                "No models installed, sir. 'pull llama3.2' gets you a good, small "
                "starting point — about 2 GB.",
                models=[],
            )

        active = self._active_model()
        router = str(getattr(self.llm, "router_model", "") or "")
        total = sum(int(entry.get("size", 0) or 0) for entry in entries)
        entries.sort(key=lambda entry: -int(entry.get("size", 0) or 0))

        lines = [f"{len(entries)} model(s), {human_bytes(total)} on disk:"]
        for entry in entries:
            name = str(entry.get("name", "?"))
            size = human_bytes(int(entry.get("size", 0) or 0))
            details = entry.get("details") or {}
            params = str(details.get("parameter_size", "") or "")
            quant = str(details.get("quantization_level", "") or "")
            marks = []
            if name == active:
                marks.append("active")
            if name == router and name != active:
                marks.append("router")
            suffix = f"  [{', '.join(marks)}]" if marks else ""
            spec = f" {params} {quant}".rstrip()
            lines.append(f"  {name:34} {size:>9}{spec}{suffix}")

        return ModuleResult(
            success=True,
            output="\n".join(lines),
            speak=f"{len(entries)} models installed, sir, using {human_bytes(total)}. "
                  f"Currently running {active or 'nothing'}.",
            data={"models": [entry.get("name") for entry in entries],
                  "active": active, "bytes": total},
        )

    @tool(
        description=(
            "Switch the model JARVIS thinks with. The model must already be installed; "
            "use pull_model first if it is not."
        ),
        params={
            "name": {"type": "string", "required": True, "description": "Model tag"},
            "permanent": {"type": "boolean", "default": False,
                          "description": "Also write it to config.yaml"},
            "role": {"type": "string", "default": "main",
                     "description": "'main' for conversation, 'router' for intent routing"},
        },
        keywords=["switch to", "use the model", "change model", "swap to",
                  "run on", "use llama", "use mistral", "use qwen", "set the model"],
        examples=['switch_model(name="mistral", permanent=true)'],
    )
    async def switch_model(self, name: str, permanent: bool = False,
                           role: str = "main") -> ModuleResult:
        """Point the brain at a different installed model.

        Args:
            name: The model tag, with or without its ``:tag`` suffix.
            permanent: Persist the choice to ``config.yaml``.
            role: ``main`` for replies, ``router`` for intent classification.

        Returns:
            Confirmation, or a suggestion to pull the model first.
        """
        wanted = (name or "").strip()
        if not wanted:
            return ModuleResult.fail("Which model, sir?")
        if self.llm is None:
            return ModuleResult.fail("There is no language model attached, sir.")

        entries = await self._tags()
        if entries is None:
            return self._offline()
        installed = [str(entry.get("name", "")) for entry in entries]
        resolved = self._match(wanted, installed)
        if resolved is None:
            catalogue = self._catalogue_entry(wanted)
            hint = (f" It is about {catalogue['size_gb']} GB." if catalogue else "")
            return ModuleResult(
                success=False,
                output=f"'{wanted}' is not installed. Installed: "
                       f"{', '.join(installed) or 'nothing'}.",
                speak=f"I don't have {wanted} installed, sir.{hint} Shall I download it?",
            ).offering(
                "models.pull_model", {"name": wanted}, f"Shall I download {wanted}?"
            )

        target = (role or "main").strip().lower()
        if target.startswith("rout"):
            previous = str(getattr(self.llm, "router_model", ""))
            self.llm.router_model = resolved
            if permanent:
                self.config.set("llm.router_model", resolved)
                self._save_config()
            return ModuleResult.ok(
                f"Routing now uses {resolved} (was {previous or 'the main model'})"
                + (", saved to config.yaml." if permanent else "."),
                model=resolved, role="router", permanent=permanent,
            )

        previous = str(getattr(self.llm, "model", ""))
        self.llm.model = resolved
        self.llm.available = True
        if permanent:
            self.config.set("llm.model", resolved)
            self._save_config()
        note = " Saved to config.yaml." if permanent else \
               " This lasts until you restart — say 'permanently' to keep it."
        return ModuleResult(
            success=True,
            output=f"Active model: {resolved} (was {previous or 'none'}).{note}",
            speak=f"Now thinking with {resolved}, sir.",
            data={"model": resolved, "previous": previous, "permanent": permanent},
        )

    @tool(
        description=(
            "Download a model from the free Ollama library. Several gigabytes and "
            "several minutes, so it confirms first."
        ),
        params={
            "name": {"type": "string", "required": True, "description": "Model tag, e.g. mistral"},
            "activate": {"type": "boolean", "default": False,
                         "description": "Switch to it once the download finishes"},
        },
        dangerous=True,
        keywords=["pull the model", "download the model", "install the model",
                  "get the model", "pull llama", "download mistral", "install qwen"],
        examples=['pull_model(name="qwen2.5:7b", activate=true)'],
    )
    async def pull_model(self, name: str, activate: bool = False) -> ModuleResult:
        """Fetch a model from the Ollama library, reporting progress.

        Args:
            name: The model tag to download.
            activate: Make it the active model afterwards.

        Returns:
            A summary of the download.
        """
        wanted = (name or "").strip()
        if not wanted:
            return ModuleResult.fail("Which model should I download, sir?")
        if self._pulling:
            return ModuleResult.fail(
                f"I am already downloading {self._pulling}, sir. One at a time."
            )

        client = await self._client()
        if client is None:
            return ModuleResult.fail("httpx is not installed, so I cannot reach Ollama.")

        catalogue = self._catalogue_entry(wanted)
        if catalogue:
            await self._status(
                f"Downloading {wanted}, sir — roughly {catalogue['size_gb']} gigabytes."
            )
        else:
            await self._status(f"Downloading {wanted}, sir.")

        self._pulling = wanted
        started = time.monotonic()
        completed = 0
        total = 0
        last_spoken = started
        error = ""
        try:
            async with client.stream(
                "POST", f"{self.host}/api/pull",
                json={"name": wanted, "stream": True},
                timeout=self.pull_timeout,
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "replace")
                    return ModuleResult.fail(
                        f"Ollama refused to pull '{wanted}': "
                        f"{truncate(body.strip() or str(response.status_code), 160)}"
                    )
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    if event.get("error"):
                        error = str(event["error"])
                        break
                    completed = int(event.get("completed", completed) or completed)
                    total = int(event.get("total", total) or total)
                    now = time.monotonic()
                    if total and now - last_spoken >= 20:
                        last_spoken = now
                        percent = min(100, int(completed * 100 / total))
                        await self._status(
                            f"{percent} percent of {human_bytes(total)}, sir."
                        )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = str(exc)
        finally:
            self._pulling = None
            await client.aclose()

        if error:
            return ModuleResult.fail(
                f"The download of '{wanted}' failed: {truncate(error, 200)}. "
                "Check the name at ollama.com/library, sir."
            )

        elapsed = human_duration(time.monotonic() - started)
        entries = await self._tags() or []
        resolved = self._match(wanted, [str(entry.get("name", "")) for entry in entries])
        if resolved is None:
            return ModuleResult.fail(
                f"Ollama reported success but '{wanted}' is not in the model list, sir."
            )

        message = f"Downloaded {resolved} in {elapsed}."
        if activate and self.llm is not None:
            self.llm.model = resolved
            self.llm.available = True
            message += " It is now the active model."
        else:
            message += f" Say 'switch to {resolved}' when you want it."
        return ModuleResult(
            success=True, output=message,
            speak=f"{resolved} is ready, sir. That took {elapsed}.",
            data={"model": resolved, "seconds": round(time.monotonic() - started, 1),
                  "activated": bool(activate)},
        )

    @tool(
        description="Delete a local model to free disk space.",
        params={"name": {"type": "string", "required": True, "description": "Model tag"}},
        dangerous=True,
        keywords=["delete the model", "remove the model", "uninstall the model",
                  "free up space models", "get rid of the model"],
        examples=['remove_model(name="llama2:13b")'],
    )
    async def remove_model(self, name: str) -> ModuleResult:
        """Remove an installed model.

        Args:
            name: The model tag to delete.

        Returns:
            Confirmation and the space reclaimed.
        """
        wanted = (name or "").strip()
        if not wanted:
            return ModuleResult.fail("Which model should I remove, sir?")

        entries = await self._tags()
        if entries is None:
            return self._offline()
        installed = {str(entry.get("name", "")): int(entry.get("size", 0) or 0)
                     for entry in entries}
        resolved = self._match(wanted, list(installed))
        if resolved is None:
            return ModuleResult.fail(f"'{wanted}' is not installed, sir.")
        if resolved == self._active_model():
            return ModuleResult.fail(
                f"{resolved} is the model I am currently thinking with, sir. "
                "Switch to another one first."
            )

        client = await self._client()
        if client is None:
            return ModuleResult.fail("httpx is not installed, so I cannot reach Ollama.")
        try:
            response = await client.request(
                "DELETE", f"{self.host}/api/delete", json={"name": resolved}
            )
            if response.status_code >= 400:
                return ModuleResult.fail(
                    f"Ollama refused to delete {resolved}: {response.status_code}."
                )
        except Exception as exc:
            return ModuleResult.fail(f"Could not delete {resolved}: {truncate(str(exc), 120)}")
        finally:
            await client.aclose()

        freed = human_bytes(installed.get(resolved, 0))
        return ModuleResult.ok(f"Deleted {resolved} — {freed} reclaimed.",
                               model=resolved, freed=installed.get(resolved, 0))

    @tool(
        description="Show the details of one model: parameters, quantisation, context length.",
        params={"name": {"type": "string", "default": "",
                         "description": "Model tag (defaults to the active one)"}},
        keywords=["model info", "about the model", "details of the model",
                  "what model are you", "which model are you running"],
    )
    async def model_info(self, name: str = "") -> ModuleResult:
        """Describe one model in detail.

        Args:
            name: Which model, defaulting to the active one.

        Returns:
            Parameter count, quantisation, family and context length.
        """
        wanted = (name or "").strip() or self._active_model()
        if not wanted:
            return ModuleResult.fail("No model is active, sir.")

        client = await self._client()
        if client is None:
            return ModuleResult.fail("httpx is not installed, so I cannot reach Ollama.")
        try:
            response = await client.post(f"{self.host}/api/show", json={"name": wanted})
            if response.status_code >= 400:
                return ModuleResult.fail(f"Ollama does not know '{wanted}', sir.")
            payload = response.json()
        except Exception as exc:
            return ModuleResult.fail(f"Could not read model details: {truncate(str(exc), 120)}")
        finally:
            await client.aclose()

        details = payload.get("details") or {}
        info = payload.get("model_info") or {}
        context = ""
        for key, value in info.items():
            if key.endswith("context_length"):
                context = f"{int(value):,} tokens"
                break
        lines = [f"{wanted}:"]
        for label, value in (
            ("family", details.get("family")),
            ("parameters", details.get("parameter_size")),
            ("quantisation", details.get("quantization_level")),
            ("context", context),
        ):
            if value:
                lines.append(f"  {label:14} {value}")
        if wanted == self._active_model():
            lines.append("  (this is the model I am thinking with)")
        return ModuleResult.ok("\n".join(lines), model=wanted, details=details)

    @tool(
        description=(
            "Recommend which free model to use for a purpose — coding, speed, "
            "reasoning, vision — given the machine's memory."
        ),
        params={"purpose": {"type": "string", "default": "general",
                            "description": "coding, fast, reasoning, vision, writing…"}},
        keywords=["which model should", "best model for", "recommend a model",
                  "what model is best", "good model for"],
        examples=['recommend_model(purpose="coding")'],
    )
    async def recommend_model(self, purpose: str = "general") -> ModuleResult:
        """Suggest suitable models for a task.

        Args:
            purpose: What the model is for.

        Returns:
            A short ranked list, marked with what is already installed.
        """
        wanted = (purpose or "general").strip().lower()
        tag = "general"
        for keyword, mapped in PURPOSE_TAGS.items():
            if keyword in wanted:
                tag = mapped
                break

        ram_gb = self._free_ram_gb()
        candidates = [entry for entry in CATALOG if tag in entry["tags"]]
        if not candidates:
            candidates = [entry for entry in CATALOG if "general" in entry["tags"]]
        affordable = [entry for entry in candidates
                      if not ram_gb or entry["ram_gb"] <= ram_gb + 0.1]
        shortlist = affordable or candidates

        entries = await self._tags()
        installed = {str(entry.get("name", "")).split(":")[0]
                     for entry in (entries or [])}

        lines = [f"For {wanted}:"]
        for entry in shortlist[:4]:
            mark = "installed" if entry["name"].split(":")[0] in installed else \
                   f"{entry['size_gb']} GB download"
            lines.append(f"  {entry['name']:24} {entry['good_at']}  ({mark}, "
                         f"wants {entry['ram_gb']} GB RAM)")
        if ram_gb:
            lines.append(f"You have about {ram_gb:.0f} GB of RAM free.")
            skipped = [entry["name"] for entry in candidates if entry not in shortlist]
            if skipped:
                lines.append(f"Too heavy for this machine right now: {', '.join(skipped)}.")

        best = shortlist[0]["name"] if shortlist else ""
        result = ModuleResult(
            success=True,
            output="\n".join(lines),
            speak=f"I would use {best} for {wanted}, sir." if best else "\n".join(lines),
            data={"purpose": tag, "recommended": best,
                  "options": [entry["name"] for entry in shortlist]},
        )
        if best and best.split(":")[0] not in installed:
            result.offering("models.pull_model", {"name": best},
                            f"Shall I download {best}? It is about "
                            f"{shortlist[0]['size_gb']} GB.")
        return result

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _match(wanted: str, installed: List[str]) -> Optional[str]:
        """Resolve a loose model name against the installed tags.

        Args:
            wanted: What the user said, e.g. ``mistral``.
            installed: Every installed tag, e.g. ``mistral:7b``.

        Returns:
            The matching tag, or ``None``.
        """
        wanted = wanted.strip()
        if not wanted:
            return None
        for tag in installed:
            if tag.lower() == wanted.lower():
                return tag
        base = wanted.split(":")[0].lower()
        for tag in installed:
            if tag.split(":")[0].lower() == base:
                return tag
        for tag in installed:
            if base and base in tag.lower():
                return tag
        return None

    @staticmethod
    def _catalogue_entry(name: str) -> Optional[Dict[str, Any]]:
        """Look a model up in the curated catalogue."""
        base = (name or "").split(":")[0].lower()
        if not base:
            return None
        for entry in CATALOG:
            if entry["name"].split(":")[0].lower() == base:
                return entry
        # "llama3" should still be recognised as a model even though the
        # catalogue lists llama3.2 and llama3.1 — people drop the point release.
        for entry in CATALOG:
            family = entry["name"].split(":")[0].lower()
            if len(base) >= 4 and (family.startswith(base) or base.startswith(family)):
                return entry
        return None

    @staticmethod
    def _free_ram_gb() -> float:
        """Available system memory in GB, or ``0.0`` when psutil is missing."""
        try:
            import psutil

            return float(psutil.virtual_memory().available) / (1024 ** 3)
        except Exception:
            return 0.0

    def _save_config(self) -> None:
        """Persist config.yaml, logging rather than raising when it fails."""
        try:
            self.config.save()
        except Exception as exc:
            self.log.warning("Could not save config.yaml: %s", exc)

    async def _status(self, message: str) -> None:
        """Send a progress update through the brain's status channel."""
        self.log.info("%s", message)
        hook = getattr(self.brain, "speaker_hook", None) if self.brain else None
        if hook is None:
            return
        try:
            result = hook(message)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:  # pragma: no cover - defensive
            self.log.debug("Status hook failed: %s", exc)

    # ----------------------------------------------------------------- router
    def offline_router(self, command: str) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Rule-based routing used when no LLM is available."""
        text = strip_command_prefix(command)
        lowered = text.lower()

        if re.search(r"\b(?:which|what)\s+model\s+(?:should|is\s+best|would|do\s+you\s+"
                     r"recommend)|best\s+model|recommend\s+a?\s*model|good\s+model\s+for",
                     lowered):
            purpose = re.sub(r".*\b(?:for|to|at)\s+", "", lowered).strip(" ?.")
            if purpose == lowered.strip(" ?."):
                purpose = "general"
            return "recommend_model", {"purpose": purpose or "general"}

        pull = re.search(r"\b(?:pull|download|install|fetch|get)\s+(?:the\s+)?(?:model\s+)?"
                         r"([\w.:\-/]+)", lowered)
        if pull and ("model" in lowered or self._catalogue_entry(pull.group(1))):
            return "pull_model", {"name": pull.group(1),
                                  "activate": "and use" in lowered or "then use" in lowered}

        remove = re.search(r"\b(?:delete|remove|uninstall|get rid of)\s+(?:the\s+)?"
                           r"(?:model\s+)?([\w.:\-/]+)", lowered)
        if remove and ("model" in lowered or self._catalogue_entry(remove.group(1))):
            return "remove_model", {"name": remove.group(1)}

        switch = re.search(r"\b(?:switch|change|swap)\s+(?:to|the model to)\s+"
                           r"(?:the\s+)?(?:model\s+)?([\w.:\-/]+)", lowered)
        if switch is None:
            switch = re.search(r"\buse\s+(?:the\s+)?([\w.:\-/]+)\s+model\b", lowered)
        if switch:
            return "switch_model", {
                "name": switch.group(1),
                "permanent": any(word in lowered for word in
                                 ("permanent", "always", "from now on", "save it", "default")),
                "role": "router" if "rout" in lowered else "main",
            }

        if any(phrase in lowered for phrase in
               ("model info", "about the model", "which model are you",
                "what model are you", "details of the model")):
            return "model_info", {}

        return "list_models", {}
