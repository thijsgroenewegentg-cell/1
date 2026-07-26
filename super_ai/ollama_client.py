"""
Ollama Client Integration for SuperAgent.
Uses the official `ollama` Python package when available,
with a REST fallback for custom endpoints.
"""
import os
import json
import time

try:
    import ollama
except ImportError:
    ollama = None

try:
    import requests
except ImportError:
    requests = None


class OllamaLLM:
    """Connects to the smartest available Ollama model."""

    DEFAULT_MODELS = [
        "qwen3-coder-next",
        "qwen2.5-coder:32b",
        "deepseek-r1:32b",
        "llama4:scout",
        "qwen3:32b",
        "qwen2.5-coder:7b",
        "deepseek-r1:14b",
    ]

    def __init__(self, model: str = None, host: str = "http://localhost:11434"):
        self.host = host
        self.model = self._resolve_model(model)
        self._client = None
        if ollama:
            try:
                # ollama python package uses localhost:11434 by default
                self._client = ollama.Client(host=host)
            except Exception as e:
                print(f"[OllamaLLM] Could not create ollama client: {e}")

    def _resolve_model(self, model: str = None) -> str:
        if model:
            return model
        # Check saved preference
        if os.path.exists(".ollama_default_model"):
            with open(".ollama_default_model") as f:
                return f.read().strip()
        # Check what's available locally
        available = self._list_local_models()
        for preferred in self.DEFAULT_MODELS:
            for a in available:
                if preferred in a or a in preferred:
                    return a
        # Fallback to first available, else first default
        return available[0] if available else self.DEFAULT_MODELS[0]

    def _list_local_models(self) -> list:
        models = []
        try:
            if self._client:
                res = self._client.list()
                for m in res.get("models", []):
                    models.append(m.get("name", m.get("model", "unknown")))
            elif requests:
                r = requests.get(f"{self.host}/api/tags", timeout=5)
                if r.status_code == 200:
                    for m in r.json().get("models", []):
                        models.append(m.get("name", m.get("model", "unknown")))
        except Exception:
            pass
        return models if models else []

    def generate(self, prompt: str, system: str = None, temperature: float = 0.7) -> str:
        """Generate a response using the smartest available model."""
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        if self._client:
            try:
                response = self._client.chat(
                    model=self.model,
                    messages=messages,
                    options={"temperature": temperature},
                )
                return response.get("message", {}).get("content", "")
            except Exception as e:
                return f"[Ollama error: {e}]"

        if requests:
            try:
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": temperature},
                }
                r = requests.post(f"{self.host}/api/chat", json=payload, timeout=120)
                if r.status_code == 200:
                    return r.json().get("message", {}).get("content", "")
                else:
                    return f"[Ollama HTTP error: {r.status_code} - {r.text}]"
            except Exception as e:
                return f"[Ollama request error: {e}]"

        return f"[Ollama not available. Model configured: {self.model}. Ensure `ollama serve` is running.]"

    def embed(self, text: str) -> list:
        """Generate embeddings for memory/RAG."""
        try:
            if self._client:
                res = self._client.embeddings(model=self.model, prompt=text)
                return res.get("embedding", [])
        except Exception:
            pass
        return []

    def is_available(self) -> bool:
        try:
            if self._client:
                self._client.list()
                return True
            if requests:
                r = requests.get(f"{self.host}/api/tags", timeout=2)
                return r.status_code == 200
        except Exception:
            return False
        return False
