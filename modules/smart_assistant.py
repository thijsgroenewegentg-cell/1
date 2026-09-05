# /modules/smart_assistant.py
"""General intelligence: Q&A with optional web RAG, maths, conversions,
translation, summarisation and creative writing."""

from __future__ import annotations

import ast
import math
import operator
import re
from typing import Any, Callable, Dict, Optional

from modules.base import BaseModule, ModuleResult, strip_command_prefix, tool
from utils.helpers import clean_text, truncate

# ---------------------------------------------------------------------------
# Safe arithmetic evaluator
# ---------------------------------------------------------------------------

_BINARY_OPS: Dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: Dict[type, Callable[[Any], Any]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_MATH_NAMES: Dict[str, Any] = {
    name: getattr(math, name)
    for name in (
        "sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "atan2", "log", "log2",
        "log10", "exp", "floor", "ceil", "factorial", "degrees", "radians", "hypot",
        "gcd", "fabs", "pow", "isqrt",
    )
    if hasattr(math, name)
}
_MATH_NAMES.update(
    {
        "pi": math.pi,
        "e": math.e,
        "tau": math.tau,
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "int": int,
        "float": float,
    }
)


def safe_eval(expression: str) -> float:
    """Evaluate an arithmetic expression without executing arbitrary code.

    Args:
        expression: e.g. ``"(3 + 4) * sqrt(16) / 2"``.

    Returns:
        The numeric result.

    Raises:
        ValueError: If the expression contains anything unsupported.
    """
    tree = ast.parse(expression, mode="eval")

    def _eval(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"Unsupported constant: {node.value!r}")
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPS:
            return _BINARY_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Name):
            if node.id in _MATH_NAMES and not callable(_MATH_NAMES[node.id]):
                return _MATH_NAMES[node.id]
            raise ValueError(f"Unknown name: {node.id}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _MATH_NAMES:
                raise ValueError("Only basic maths functions are allowed")
            function = _MATH_NAMES[node.func.id]
            if not callable(function):
                raise ValueError(f"{node.func.id} is not callable")
            return function(*[_eval(argument) for argument in node.args])
        if isinstance(node, (ast.Tuple, ast.List)):
            return [_eval(element) for element in node.elts]
        if isinstance(node, ast.Compare):
            left = _eval(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = _eval(comparator)
                comparison = {
                    ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
                    ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne,
                }.get(type(op))
                if comparison is None or not comparison(left, right):
                    return False
                left = right
            return True
        raise ValueError(f"Unsupported expression element: {type(node).__name__}")

    return _eval(tree)


# ---------------------------------------------------------------------------
# Unit conversion tables (everything relative to a base unit)
# ---------------------------------------------------------------------------

UNIT_TABLE: Dict[str, Dict[str, float]] = {
    "length": {
        "mm": 0.001, "millimeter": 0.001, "millimeters": 0.001, "millimetre": 0.001,
        "cm": 0.01, "centimeter": 0.01, "centimeters": 0.01, "centimetre": 0.01,
        "m": 1.0, "meter": 1.0, "meters": 1.0, "metre": 1.0, "metres": 1.0,
        "km": 1000.0, "kilometer": 1000.0, "kilometers": 1000.0, "kilometre": 1000.0,
        "in": 0.0254, "inch": 0.0254, "inches": 0.0254,
        "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
        "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
        "mi": 1609.344, "mile": 1609.344, "miles": 1609.344,
        "nmi": 1852.0, "nautical mile": 1852.0,
    },
    "mass": {
        "mg": 1e-6, "milligram": 1e-6, "g": 0.001, "gram": 0.001, "grams": 0.001,
        "kg": 1.0, "kilogram": 1.0, "kilograms": 1.0, "kilo": 1.0, "kilos": 1.0,
        "t": 1000.0, "tonne": 1000.0, "tonnes": 1000.0,
        "oz": 0.0283495, "ounce": 0.0283495, "ounces": 0.0283495,
        "lb": 0.453592, "lbs": 0.453592, "pound": 0.453592, "pounds": 0.453592,
        "stone": 6.35029, "stones": 6.35029,
    },
    "volume": {
        "ml": 0.001, "milliliter": 0.001, "millilitre": 0.001,
        "l": 1.0, "liter": 1.0, "litre": 1.0, "liters": 1.0, "litres": 1.0,
        "cup": 0.236588, "cups": 0.236588,
        "pint": 0.473176, "pints": 0.473176,
        "quart": 0.946353, "quarts": 0.946353,
        "gal": 3.78541, "gallon": 3.78541, "gallons": 3.78541,
        "floz": 0.0295735, "fluid ounce": 0.0295735,
        "tbsp": 0.0147868, "tablespoon": 0.0147868,
        "tsp": 0.00492892, "teaspoon": 0.00492892,
    },
    "time": {
        "ms": 0.001, "millisecond": 0.001, "s": 1.0, "sec": 1.0, "second": 1.0,
        "seconds": 1.0, "min": 60.0, "minute": 60.0, "minutes": 60.0,
        "h": 3600.0, "hr": 3600.0, "hour": 3600.0, "hours": 3600.0,
        "day": 86400.0, "days": 86400.0, "week": 604800.0, "weeks": 604800.0,
        "month": 2629800.0, "months": 2629800.0, "year": 31557600.0, "years": 31557600.0,
    },
    "speed": {
        "m/s": 1.0, "mps": 1.0, "kph": 0.277778, "km/h": 0.277778, "kmh": 0.277778,
        "mph": 0.44704, "knot": 0.514444, "knots": 0.514444,
    },
    "data": {
        "b": 1.0, "byte": 1.0, "bytes": 1.0, "kb": 1024.0, "kilobyte": 1024.0,
        "mb": 1024.0**2, "megabyte": 1024.0**2, "gb": 1024.0**3, "gigabyte": 1024.0**3,
        "tb": 1024.0**4, "terabyte": 1024.0**4, "pb": 1024.0**5,
        "bit": 0.125, "bits": 0.125, "kbit": 128.0, "mbit": 131072.0,
    },
}

TEMPERATURE_UNITS = {"c", "celsius", "f", "fahrenheit", "k", "kelvin", "°c", "°f"}


class SmartAssistant(BaseModule):
    """Reasoning, maths, conversions, translation and writing."""

    name = "smart_assistant"
    description = (
        "General intelligence: answer questions (using the web when the answer must be "
        "current), do maths, convert units and currencies, translate text, summarise "
        "long text, and write creatively."
    )
    intent_examples = [
        "what is the meaning of life",
        "convert 10 miles to kilometres",
        "translate good morning into Japanese",
        "write a haiku about debugging",
    ]

    def __init__(self, config: Any, llm: Any = None, security: Any = None) -> None:
        """Cache the persona settings used in creative prompts."""
        super().__init__(config, llm=llm, security=security)
        self._web: Optional[Any] = None

    def _require_llm(self) -> Optional[ModuleResult]:
        """Return an error result if the LLM is unavailable."""
        if self.llm is None or not getattr(self.llm, "available", False):
            return ModuleResult.fail(
                "That one needs the language model, and Ollama isn't answering. "
                "Try 'ollama serve'."
            )
        return None

    def _web_module(self) -> Optional[Any]:
        """Lazily create a WebSearch instance for retrieval-augmented answers."""
        if self._web is None and self.config.get("modules.web_search", True):
            try:
                from modules.web_search import WebSearch

                self._web = WebSearch(self.config, llm=self.llm, security=self.security)
            except Exception as exc:
                self.log.debug("Web module unavailable: %s", exc)
                self._web = None
        return self._web

    # ---------------------------------------------------------- offline route
    def offline_router(self, command: str) -> Optional[tuple[str, Dict[str, Any]]]:
        """Rule-based routing with parameter extraction (used without an LLM)."""
        text = strip_command_prefix(command)
        lowered = text.lower()

        maths = re.search(
            r"\b(?:calculate|compute|what(?:'s| is)|how much is|evaluate|solve)\s+(.+)", lowered
        )
        if maths and re.search(r"[\d]", maths.group(1)):
            return "calculate", {"expression": maths.group(1).strip(" ?")}
        if re.fullmatch(r"[\d\s+\-*/^%().,]+", lowered.strip(" ?")) and any(
            symbol in lowered for symbol in "+-*/^%"
        ):
            return "calculate", {"expression": text.strip(" ?")}

        conversion = re.search(
            r"(?:convert\s+)?([\d.,]+)\s*([a-z°/]+(?:\s[a-z]+)?)\s+(?:in|to|into)\s+([a-z°/]+(?:\s[a-z]+)?)",
            lowered,
        )
        if conversion and ("convert" in lowered or " to " in lowered or " in " in lowered):
            try:
                return "convert", {
                    "value": float(conversion.group(1).replace(",", "")),
                    "from_unit": conversion.group(2).strip(),
                    "to_unit": conversion.group(3).strip(),
                }
            except ValueError:
                pass

        translate = re.search(
            r"translate\s+(.+?)\s+(?:in|into|to)\s+([a-z]+)\s*$", lowered
        )
        if translate:
            start = lowered.index(translate.group(1))
            return "translate", {
                "text": text[start : start + len(translate.group(1))].strip("\"' "),
                "target_language": translate.group(2),
            }

        if any(phrase in lowered for phrase in ("write a poem", "write a story", "haiku",
                                                "limerick", "write an email", "draft a")):
            return "write_creative", {"brief": text}

        if any(phrase in lowered for phrase in ("brainstorm", "give me ideas", "ideas for",
                                                "ways to")):
            return "brainstorm", {"topic": text}

        if lowered.startswith(("summarize", "summarise", "tldr")):
            return "summarize", {"text": text}

        if lowered.startswith(("define ", "definition of", "what does the word")):
            return "define", {"term": re.sub(r"^(define|definition of|what does the word)\s+",
                                             "", text, flags=re.IGNORECASE).strip(" ?")}

        if " vs " in lowered or "compare" in lowered or "pros and cons" in lowered:
            return "compare", {"items": text}

        return "answer", {"question": text}

    # ---------------------------------------------------------------- answer
    @tool(
        description="Answer a question, searching the web first when freshness matters.",
        params={
            "question": {"type": "string", "description": "The question", "required": True},
            "use_web": {
                "type": "boolean",
                "description": "Force a web search before answering",
                "default": False,
            },
        },
        keywords=["what is", "why is", "how does", "explain", "tell me", "meaning of",
                  "difference between", "should i"],
        examples=['answer(question="what is the meaning of life")'],
    )
    async def answer(self, question: str, use_web: bool = False) -> ModuleResult:
        """Answer a question with the LLM, optionally grounded in web results."""
        error = self._require_llm()
        if error:
            return error
        query = (question or "").strip()
        if not query:
            return ModuleResult.fail("Ask me something, sir.")

        needs_web = use_web or self._needs_fresh_data(query)
        context = ""
        sources: list[str] = []
        if needs_web:
            web = self._web_module()
            if web is not None:
                search = await web.search(query, max_results=4)
                if search.success and search.data.get("results"):
                    rows = search.data["results"]
                    sources = [row["url"] for row in rows]
                    context = "\n".join(
                        f"- {row['title']}: {truncate(row['snippet'], 260)} ({row['url']})"
                        for row in rows
                    )

        prompt = (
            (f"Web results:\n{context}\n\n" if context else "")
            + f"Question: {query}\n\n"
            + (
                "Answer using the web results above where relevant, in 3-5 sentences."
                if context
                else "Answer in 3-5 sentences. If you are unsure, say so plainly."
            )
        )
        reply = await self.llm.complete(prompt, temperature=0.5, max_tokens=550)
        if not reply.strip():
            return ModuleResult.fail("The model returned nothing useful.")
        return ModuleResult(success=True, output=reply.strip(), data={"sources": sources})

    @staticmethod
    def _needs_fresh_data(text: str) -> bool:
        """Heuristic: does answering this require current information?"""
        lowered = text.lower()
        triggers = (
            "today", "current", "latest", "right now", "this week", "this year", "2025",
            "2026", "news", "price of", "stock", "who won", "score", "release date",
            "weather", "recent", "just happened",
        )
        return any(trigger in lowered for trigger in triggers)

    # ----------------------------------------------------------------- maths
    @tool(
        description="Evaluate a mathematical expression or a word problem.",
        params={
            "expression": {
                "type": "string",
                "description": "e.g. '15% of 240' or 'sqrt(144) + 3^2'",
                "required": True,
            }
        },
        keywords=["calculate", "what's", "how much is", "math", "sum of", "multiply",
                  "divide", "percent of", "square root"],
        examples=['calculate(expression="15% of 240")'],
    )
    async def calculate(self, expression: str) -> ModuleResult:
        """Do arithmetic safely, falling back to the LLM for word problems."""
        raw = (expression or "").strip()
        if not raw:
            return ModuleResult.fail("Calculate what, exactly?")

        normalised = self._normalise_expression(raw)
        try:
            value = safe_eval(normalised)
            if isinstance(value, float):
                rendered = f"{value:,.10g}"
            else:
                rendered = f"{value:,}" if isinstance(value, int) else str(value)
            return ModuleResult(
                success=True,
                output=f"{raw} = {rendered}",
                speak=f"That's {rendered}.",
                data={"expression": normalised, "result": value},
            )
        except Exception as exc:
            self.log.debug("safe_eval failed for %r: %s", normalised, exc)

        error = self._require_llm()
        if error:
            return ModuleResult.fail(
                f"I couldn't parse '{raw}' as arithmetic, and the LLM is offline for the "
                "word-problem route."
            )
        reply = await self.llm.complete(
            f"Solve this and show the final numeric answer on its own last line:\n{raw}",
            temperature=0.0,
            max_tokens=400,
        )
        return ModuleResult(success=bool(reply.strip()), output=reply.strip() or "No answer.")

    @staticmethod
    def _normalise_expression(text: str) -> str:
        """Turn spoken maths into Python syntax."""
        expression = text.lower().strip().rstrip("?")
        for prefix in ("calculate", "compute", "what is", "what's", "how much is", "evaluate",
                       "solve"):
            if expression.startswith(prefix):
                expression = expression[len(prefix):].strip()
        percent_of = re.match(r"^([\d.]+)\s*%\s*of\s*([\d.,]+)$", expression)
        if percent_of:
            base = percent_of.group(2).replace(",", "")
            return f"({percent_of.group(1)}/100)*{base}"
        replacements = {
            "plus": "+", "minus": "-", "times": "*", "multiplied by": "*",
            "divided by": "/", "over": "/", "to the power of": "**", "squared": "**2",
            "cubed": "**3", "mod": "%", "^": "**", "×": "*", "÷": "/", "π": "pi",
        }
        for word, symbol in replacements.items():
            expression = expression.replace(word, symbol)
        expression = re.sub(r"(\d),(\d{3})", r"\1\2", expression)
        expression = re.sub(r"[^\d\s+\-*/%().,a-z_]", "", expression)
        return expression.strip()

    # ------------------------------------------------------------ conversion
    @tool(
        description="Convert between units (length, mass, volume, time, speed, data, temperature).",
        params={
            "value": {"type": "number", "description": "Amount", "required": True},
            "from_unit": {"type": "string", "description": "Source unit", "required": True},
            "to_unit": {"type": "string", "description": "Target unit", "required": True},
        },
        keywords=["convert", "how many kilometers", "in celsius", "to fahrenheit", "in pounds",
                  "how many miles"],
        examples=['convert(value=10, from_unit="miles", to_unit="km")'],
    )
    async def convert(self, value: float, from_unit: str, to_unit: str) -> ModuleResult:
        """Convert a quantity between two units."""
        try:
            amount = float(value)
        except Exception:
            return ModuleResult.fail("The amount must be a number.")

        source = str(from_unit).strip().lower().rstrip(".")
        target = str(to_unit).strip().lower().rstrip(".")

        if source in TEMPERATURE_UNITS and target in TEMPERATURE_UNITS:
            result = self._convert_temperature(amount, source, target)
            if result is None:
                return ModuleResult.fail("I couldn't convert those temperature units.")
            return ModuleResult(
                success=True,
                output=f"{amount:g}°{source[0].upper()} = {result:.2f}°{target[0].upper()}",
                speak=f"{amount:g} degrees {source} is {result:.1f} degrees {target}.",
                data={"result": result},
            )

        for category, table in UNIT_TABLE.items():
            if source in table and target in table:
                converted = amount * table[source] / table[target]
                rendered = f"{converted:,.6g}"
                return ModuleResult(
                    success=True,
                    output=f"{amount:g} {from_unit} = {rendered} {to_unit} ({category})",
                    speak=f"{amount:g} {from_unit} is {rendered} {to_unit}.",
                    data={"result": converted, "category": category},
                )

        currency = await self._convert_currency(amount, source.upper(), target.upper())
        if currency is not None:
            return currency

        error = self._require_llm()
        if error:
            return ModuleResult.fail(f"I don't know how to convert {from_unit} to {to_unit}.")
        reply = await self.llm.complete(
            f"Convert {amount} {from_unit} to {to_unit}. Give the number and unit only.",
            temperature=0.0,
            max_tokens=100,
        )
        return ModuleResult(success=bool(reply.strip()), output=reply.strip() or "Unknown units.")

    @staticmethod
    def _convert_temperature(value: float, source: str, target: str) -> Optional[float]:
        """Convert between Celsius, Fahrenheit and Kelvin."""
        source = source.lstrip("°")[0]
        target = target.lstrip("°")[0]
        celsius = (
            value if source == "c" else
            (value - 32) * 5 / 9 if source == "f" else
            value - 273.15 if source == "k" else None
        )
        if celsius is None:
            return None
        if target == "c":
            return celsius
        if target == "f":
            return celsius * 9 / 5 + 32
        if target == "k":
            return celsius + 273.15
        return None

    async def _convert_currency(
        self, amount: float, source: str, target: str
    ) -> Optional[ModuleResult]:
        """Convert currency using a free, key-less exchange rate API."""
        if len(source) != 3 or len(target) != 3:
            return None
        try:
            import httpx

            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get(
                    f"https://api.frankfurter.app/latest?amount={amount}"
                    f"&from={source}&to={target}"
                )
                response.raise_for_status()
                rates = response.json().get("rates", {})
                if target in rates:
                    converted = float(rates[target])
                    return ModuleResult(
                        success=True,
                        output=f"{amount:,.2f} {source} = {converted:,.2f} {target}",
                        speak=f"{amount:,.2f} {source} is about {converted:,.2f} {target}.",
                        data={"result": converted},
                    )
        except Exception as exc:
            self.log.debug("Currency lookup failed: %s", exc)
        return None

    # ------------------------------------------------------------ translation
    @tool(
        description="Translate text into another language.",
        params={
            "text": {"type": "string", "description": "Text to translate", "required": True},
            "target_language": {
                "type": "string",
                "description": "Target language",
                "required": True,
            },
        },
        keywords=["translate", "in spanish", "in french", "in german", "how do you say",
                  "in japanese", "in dutch"],
    )
    async def translate(self, text: str, target_language: str) -> ModuleResult:
        """Translate text using the local LLM."""
        error = self._require_llm()
        if error:
            return error
        body = (text or "").strip()
        if not body:
            return ModuleResult.fail("Translate what?")
        reply = await self.llm.complete(
            f"Translate the following into {target_language}. Output only the translation, "
            f"then on a second line a simple pronunciation hint if the script is non-Latin.\n\n"
            f"{body}",
            temperature=0.2,
            max_tokens=500,
        )
        cleaned = clean_text(reply)
        return ModuleResult(
            success=bool(cleaned),
            output=cleaned or "Translation failed.",
            data={"target": target_language},
        )

    # ---------------------------------------------------------- summarisation
    @tool(
        description="Summarise a block of text.",
        params={
            "text": {"type": "string", "description": "Text to summarise", "required": True},
            "style": {
                "type": "string",
                "description": "bullets, paragraph or tldr",
                "default": "bullets",
            },
        },
        keywords=["summarize", "summarise", "tldr", "condense", "shorten this", "key points"],
    )
    async def summarize(self, text: str, style: str = "bullets") -> ModuleResult:
        """Condense text into bullets, a paragraph or a one-liner."""
        error = self._require_llm()
        if error:
            return error
        body = (text or "").strip()
        if len(body) < 40:
            return ModuleResult.fail("That's already short enough, sir.")
        instruction = {
            "bullets": "Summarise as at most 5 concise bullet points.",
            "paragraph": "Summarise in one tight paragraph of 3-4 sentences.",
            "tldr": "Summarise in a single sentence.",
        }.get(str(style).lower(), "Summarise as at most 5 concise bullet points.")
        reply = await self.llm.complete(
            f"{instruction}\n\nTEXT:\n{truncate(body, 12000)}", temperature=0.3, max_tokens=600
        )
        return ModuleResult.ok(reply.strip() or "Summary failed.")

    # ------------------------------------------------------------- creativity
    @tool(
        description="Write something creative: a poem, story, email, speech or post.",
        params={
            "brief": {"type": "string", "description": "What to write", "required": True},
            "form": {
                "type": "string",
                "description": "poem, story, email, tweet, speech…",
                "default": "short piece",
            },
            "tone": {"type": "string", "description": "Desired tone", "default": "engaging"},
        },
        keywords=["write a poem", "write a story", "write an email", "draft a", "compose",
                  "haiku", "limerick", "speech about"],
    )
    async def write_creative(
        self, brief: str, form: str = "short piece", tone: str = "engaging"
    ) -> ModuleResult:
        """Produce creative writing to a brief."""
        error = self._require_llm()
        if error:
            return error
        topic = (brief or "").strip()
        if not topic:
            return ModuleResult.fail("Give me something to write about.")
        reply = await self.llm.complete(
            f"Write a {form} about: {topic}\nTone: {tone}. Keep it tight and vivid; "
            "no preamble, no explanation, just the piece.",
            temperature=0.9,
            max_tokens=800,
        )
        return ModuleResult.ok(reply.strip() or "The muse declined.")

    @tool(
        description="Brainstorm ideas or options for a problem.",
        params={
            "topic": {"type": "string", "description": "The problem or topic", "required": True},
            "count": {"type": "integer", "description": "How many ideas", "default": 7},
        },
        keywords=["brainstorm", "give me ideas", "options for", "ways to", "suggestions for"],
    )
    async def brainstorm(self, topic: str, count: int = 7) -> ModuleResult:
        """Generate a numbered list of ideas."""
        error = self._require_llm()
        if error:
            return error
        reply = await self.llm.complete(
            f"Brainstorm {int(count)} distinct, practical ideas for: {topic}. "
            "One line each, numbered, no preamble. Include at least one unconventional option.",
            temperature=0.95,
            max_tokens=600,
        )
        return ModuleResult.ok(reply.strip() or "No ideas surfaced.")

    @tool(
        description="Define a word or explain a term simply.",
        params={
            "term": {"type": "string", "description": "Word or phrase", "required": True},
            "level": {
                "type": "string",
                "description": "child, normal or expert",
                "default": "normal",
            },
        },
        keywords=["define", "what does the word", "meaning of the word", "definition of"],
    )
    async def define(self, term: str, level: str = "normal") -> ModuleResult:
        """Define a term at the requested level of sophistication."""
        error = self._require_llm()
        if error:
            return error
        audience = {
            "child": "Explain as if to a bright ten-year-old.",
            "expert": "Explain precisely, using correct technical vocabulary.",
        }.get(str(level).lower(), "Explain clearly for a general audience.")
        reply = await self.llm.complete(
            f"Define '{term}'. {audience} Two or three sentences, then one example.",
            temperature=0.3,
            max_tokens=350,
        )
        return ModuleResult.ok(reply.strip() or f"No definition found for '{term}'.")

    @tool(
        description="Compare two or more things and give a recommendation.",
        params={
            "items": {"type": "string", "description": "Things to compare", "required": True},
            "criteria": {
                "type": "string",
                "description": "What matters most",
                "default": "overall value",
            },
        },
        keywords=["compare", "versus", " vs ", "pros and cons", "which is better"],
    )
    async def compare(self, items: str, criteria: str = "overall value") -> ModuleResult:
        """Compare options against criteria and recommend one."""
        error = self._require_llm()
        if error:
            return error
        reply = await self.llm.complete(
            f"Compare: {items}\nCriteria: {criteria}\n"
            "Give a short pros/cons for each, then one clear recommendation with a reason.",
            temperature=0.4,
            max_tokens=700,
        )
        return ModuleResult.ok(reply.strip() or "Comparison failed.")


__all__ = ["SmartAssistant", "safe_eval"]
