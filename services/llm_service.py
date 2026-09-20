"""
services/llm_service.py
------------------------
LLM factory — supports OpenRouter (primary) + Groq (fallback).
Fallback chain: OpenRouter → Groq → knowledge-base extractive answer.

Fixes in this revision
----------------------
* `call_llm_with_fallback()` now accepts the *system prompt* that the caller
  selected (report / lab / x-ray / generic). Previously every call used one
  hard-coded prompt, so report mode and lab mode produced identical answers.
* Failures are no longer silent. The returned dict carries `_degraded` and
  `_error` so the API and the UI can tell the user the model did not answer
  instead of printing a canned paragraph that looks like a real reply.
* The offline fallback is now *extractive*: it answers from the retrieved
  knowledge-base context, so different questions produce different text even
  when no API key is configured.
* JSON parsing is brace-balanced and repairs the common model mistakes
  (code fences, `json` prefix, trailing commas, smart quotes).
"""

import os
import re
import json
import logging
from typing import Optional, Tuple

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

REQUIRED_KEYS = (
    "problem_summary",
    "possible_conditions",
    "severity_level",
    "recommendations",
    "when_to_seek_help",
)

VALID_SEVERITIES = ("low", "moderate", "high")

DISCLAIMER = (
    "⚠️ This is AI-generated information. Always consult a qualified "
    "healthcare professional for diagnosis and treatment."
)


# ══════════════════════════════════════════════════════════════════════════════
# LLM factory
# ══════════════════════════════════════════════════════════════════════════════

def _key(name: str) -> str:
    """Return a configured API key, treating placeholders as 'not set'."""
    value = os.environ.get(name, "").strip().strip('"').strip("'")
    if not value or value.lower().startswith("your_") or value.lower() in {"none", "changeme"}:
        return ""
    return value


def get_llm():
    """
    Return the appropriate LLM. Priority: OpenRouter → Groq → RuntimeError.
    Interface preserved — callers that want a non-fatal probe use try_get_llm().
    """
    openrouter_key = _key("OPENROUTER_API_KEY")
    if openrouter_key:
        model = os.environ.get("OPENROUTER_MODEL", "google/gemma-3-27b-it:free")
        logger.info(f"[LLM] Using OpenRouter: {model}")
        try:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=model,
                api_key=openrouter_key,
                base_url="https://openrouter.ai/api/v1",
                temperature=0.3,
                max_tokens=1024,
                timeout=60,
                max_retries=2,
                default_headers={
                    "HTTP-Referer": "http://localhost:5000",
                    "X-Title": "MediBot Medical Assistant",
                },
            )
        except Exception as e:
            logger.error(f"[LLM] OpenRouter init failed: {e}")

    groq_key = _key("GROQ_API_KEY")
    if groq_key:
        model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        logger.info(f"[LLM] Using Groq: {model}")
        try:
            from langchain_groq import ChatGroq
            return ChatGroq(
                model=model, api_key=groq_key,
                temperature=0.3, max_tokens=1024, timeout=60, max_retries=2,
            )
        except Exception as e:
            logger.error(f"[LLM] Groq init failed: {e}")

    raise RuntimeError(
        "No LLM configured! Set one of these in your .env:\n"
        "  OPENROUTER_API_KEY=sk-or-v1-...  (free: https://openrouter.ai/keys)\n"
        "  GROQ_API_KEY=gsk_...             (free: https://console.groq.com)"
    )


def try_get_llm() -> Tuple[Optional[object], str]:
    """
    Non-fatal variant of get_llm(). Returns (llm_or_None, error_message).
    Lets the app start in knowledge-base-only mode instead of dying at import
    time — a dead app was what made every request fall through to the same
    canned response.
    """
    try:
        return get_llm(), ""
    except Exception as e:
        logger.error(f"[LLM] No usable LLM: {e}")
        return None, str(e)


# ══════════════════════════════════════════════════════════════════════════════
# Prompt rendering
# ══════════════════════════════════════════════════════════════════════════════

def render_prompt(template: str, **fields) -> str:
    """
    Fill a system-prompt template for a direct (non-LangChain) call.

    The prompt templates double their JSON braces (`{{`/`}}`) because they are
    also fed to ChatPromptTemplate. When we call the model directly we must
    substitute the real placeholders first and then undouble the braces, or the
    model is shown `{{` and copies it into its answer.
    """
    out = template
    for key, value in fields.items():
        out = out.replace("{" + key + "}", str(value))
    return out.replace("{{", "{").replace("}}", "}")


DEFAULT_SYSTEM_PROMPT = """You are MediBot, an expert AI medical assistant.

Retrieved medical context from the knowledge base:
{context}

INSTRUCTIONS:
1. Answer the user's specific question. Do not give a generic answer.
2. Use the retrieved context when it is relevant, and name the source you used.
3. If the context does not cover the question, answer from general medical
   knowledge and say so — never invent a citation.
4. Use plain language a patient can understand.
5. Never fabricate drug doses, test values, or specific prescriptions.
6. Return ONLY valid JSON — no markdown fences, no commentary.

REQUIRED OUTPUT FORMAT (strict JSON, exactly these keys):
{
  "problem_summary": "2-3 sentences answering this specific question",
  "possible_conditions": ["Condition 1", "Condition 2", "Condition 3"],
  "severity_level": "low",
  "recommendations": ["Step 1", "Step 2", "Step 3"],
  "when_to_seek_help": "Specific warning signs requiring prompt medical care"
}

severity_level must be exactly: low, moderate, or high
possible_conditions: 2-4 items. recommendations: 3-5 specific, actionable steps."""


# ══════════════════════════════════════════════════════════════════════════════
# Response parsing
# ══════════════════════════════════════════════════════════════════════════════

def _strip_fences(text: str) -> str:
    """Remove markdown code fences and a leading `json` language tag."""
    text = text.strip()
    if "```" in text:
        blocks = re.findall(r"```(?:[a-zA-Z]*)\n?(.*?)```", text, re.DOTALL)
        for block in blocks:
            if "{" in block:
                return block.strip()
        text = text.replace("```", " ")
    return re.sub(r"^\s*json\s*", "", text, flags=re.IGNORECASE)


def _balanced_json_slice(text: str) -> str:
    """
    Return the first complete, brace-balanced JSON object in `text`.
    A plain find('{') / rfind('}') breaks whenever the model adds prose
    containing braces after the object.
    """
    start = text.find("{")
    if start < 0:
        return ""
    depth, in_string, escaped = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]  # truncated output — let the repair pass try


def _close_unterminated(text: str) -> str:
    """
    Close a truncated JSON document — models cut off mid-answer when they hit
    max_tokens. Delimiters must be closed in reverse nesting order, so this
    walks the text with a stack rather than counting braces and brackets
    independently.
    """
    stack, in_string, escaped = [], False, False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()

    if not stack and not in_string:
        return text

    fixed = text + ('"' if in_string else "")
    # Drop a dangling key or separator left behind by the cut-off
    fixed = re.sub(r'[,:]\s*$', "", fixed)
    fixed = re.sub(r',\s*"[^"]*"\s*:\s*$', "", fixed)
    for opener in reversed(stack):
        fixed += "}" if opener == "{" else "]"
    return fixed


def _repair_json(candidate: str) -> str:
    """Fix the mistakes models actually make in 'strict JSON' output."""
    fixed = candidate.replace("\u201c", '"').replace("\u201d", '"')
    fixed = fixed.replace("\u2018", "'").replace("\u2019", "'")
    fixed = re.sub(r"}\s*{", "},{", fixed)                # missing separators
    fixed = _close_unterminated(fixed)                    # truncated output
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)          # trailing commas
    return fixed


def parse_llm_response(text: str) -> dict:
    """Parse a model reply into a dict. Raises ValueError if nothing usable."""
    if not text or not text.strip():
        raise ValueError("empty model response")

    candidate = _balanced_json_slice(_strip_fences(text))
    if not candidate:
        raise ValueError("no JSON object found in model response")

    for attempt in (candidate, _repair_json(candidate)):
        try:
            parsed = json.loads(attempt)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    raise ValueError("model response was not valid JSON")


def _as_list(value, fallback: list) -> list:
    """Coerce whatever the model returned into a clean list of strings."""
    if isinstance(value, str):
        parts = [p.strip(" -•\t") for p in re.split(r"\n+|(?<=[.;])\s{2,}", value)]
        value = [p for p in parts if p]
    if isinstance(value, dict):
        value = list(value.values())
    if not isinstance(value, list):
        return fallback
    cleaned = [str(v).strip() for v in value if str(v).strip()]
    return cleaned or fallback


def normalize_structured(raw: dict, query: str, context: str = "") -> dict:
    """Guarantee the five keys, correct types, and a valid severity level."""
    fallback = _extractive_structured(query, context, reason="")
    result = dict(raw)

    summary = str(result.get("problem_summary", "")).strip()
    result["problem_summary"] = summary or fallback["problem_summary"]

    result["possible_conditions"] = _as_list(
        result.get("possible_conditions"), fallback["possible_conditions"]
    )[:4]
    result["recommendations"] = _as_list(
        result.get("recommendations"), fallback["recommendations"]
    )[:5]

    severity = str(result.get("severity_level", "")).strip().lower()
    severity = next((s for s in VALID_SEVERITIES if s in severity), "moderate")
    result["severity_level"] = severity

    when = str(result.get("when_to_seek_help", "")).strip()
    result["when_to_seek_help"] = when or fallback["when_to_seek_help"]
    if "⚠️" not in result["when_to_seek_help"]:
        result["when_to_seek_help"] += f" {DISCLAIMER}"

    result["_degraded"] = False
    result["_error"] = None
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ══════════════════════════════════════════════════════════════════════════════

def call_llm_with_fallback(
    llm,
    prompt: str,
    context: str = "",
    system_prompt: Optional[str] = None,
    prompt_fields: Optional[dict] = None,
) -> dict:
    """
    Call the LLM and always return a structured dict. Never raises.

    Args:
        llm:            primary LangChain chat model (may be None)
        prompt:         the user's actual question / augmented query
        context:        retrieved knowledge-base text
        system_prompt:  mode-specific template (report / lab / x-ray). The
                        template's {context} and any extra placeholders are
                        filled in here. Falls back to the generic prompt.
        prompt_fields:  extra placeholder values, e.g. {"lab_values": ...}
    """
    fields = {"context": context or "(no knowledge-base context retrieved)"}
    fields.update(prompt_fields or {})

    rendered_system = render_prompt(system_prompt or DEFAULT_SYSTEM_PROMPT, **fields)
    full_prompt = f"{rendered_system}\n\nUSER QUERY:\n{prompt}\n\nRespond now with the JSON object only."

    errors = []

    # ── Primary LLM ───────────────────────────────────────────────────────────
    if llm is not None:
        try:
            from langchain_core.messages import HumanMessage
            response = llm.invoke([HumanMessage(content=full_prompt)])
            result = normalize_structured(parse_llm_response(response.content), prompt, context)
            logger.info("[LLM] Primary LLM call succeeded.")
            return result
        except Exception as e:
            errors.append(f"primary: {e}")
            logger.warning(f"[LLM] Primary LLM call failed: {e}. Trying Groq fallback...")
    else:
        errors.append("primary: no LLM configured")

    # ── Groq fallback ─────────────────────────────────────────────────────────
    groq_key = _key("GROQ_API_KEY")
    if groq_key:
        try:
            from langchain_groq import ChatGroq
            from langchain_core.messages import HumanMessage
            fallback_llm = ChatGroq(
                model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
                api_key=groq_key, temperature=0.3, max_tokens=1024,
                timeout=60, max_retries=1,
            )
            response = fallback_llm.invoke([HumanMessage(content=full_prompt)])
            result = normalize_structured(parse_llm_response(response.content), prompt, context)
            logger.info("[LLM] Groq fallback succeeded.")
            return result
        except Exception as fe:
            errors.append(f"groq: {fe}")
            logger.error(f"[LLM] Groq fallback failed: {fe}")

    # ── Offline: answer from retrieved context ────────────────────────────────
    reason = " | ".join(errors) or "no provider available"
    logger.warning(f"[LLM] All providers failed ({reason}). Returning knowledge-base answer.")
    return _extractive_structured(prompt, context, reason=reason, degraded=True)


# ══════════════════════════════════════════════════════════════════════════════
# Offline / extractive fallback
# ══════════════════════════════════════════════════════════════════════════════

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _clean_query(query: str) -> str:
    """Strip the report marker block so the echoed query stays readable."""
    query = re.sub(r"\[MEDICAL REPORT CONTENT\]|\[PATIENT QUESTION\]", " ", query or "")
    return re.sub(r"\s+", " ", query).strip()


def _relevant_sentences(query: str, context: str, limit: int = 6) -> list:
    """
    Pick the context sentences that overlap most with the query.
    This is what makes the offline answer differ per question instead of
    repeating one canned paragraph.
    """
    if not context:
        return []

    stop = {
        "what", "why", "how", "does", "the", "and", "for", "with", "you", "your",
        "are", "is", "can", "should", "have", "has", "was", "were", "this", "that",
        "from", "about", "when", "which", "there", "their", "them", "will", "would",
        "please", "tell", "give", "any", "all", "not", "but", "its", "it's",
    }
    terms = {w for w in re.findall(r"[a-z]{3,}", _clean_query(query).lower()) if w not in stop}
    if not terms:
        return []

    scored = []
    for line in context.split("\n"):
        for sentence in _SENTENCE_SPLIT.split(line):
            sentence = sentence.strip()
            if len(sentence) < 40 or sentence.startswith("[Source:"):
                continue
            words = set(re.findall(r"[a-z]{3,}", sentence.lower()))
            overlap = len(terms & words)
            if overlap:
                scored.append((overlap, sentence))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    seen, picked = set(), []
    for _, sentence in scored:
        key = sentence[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        picked.append(sentence if len(sentence) < 320 else sentence[:317] + "...")
        if len(picked) >= limit:
            break
    return picked


def _extractive_structured(query: str, context: str = "", reason: str = "",
                           degraded: bool = False) -> dict:
    """
    Build a structured answer without the LLM.

    With knowledge-base context this returns the passages that actually match
    the question — a different answer per question. Without context it states
    plainly that the AI model is unavailable rather than pretending to answer.
    """
    shown_query = _clean_query(query)[:160] or "your query"
    sentences = _relevant_sentences(query, context)

    if sentences:
        summary = (
            f"The AI model could not be reached, so this answer is taken directly "
            f"from the medical knowledge base for: \"{shown_query}\".\n\n"
            + " ".join(sentences[:2])
        )
        conditions = ["See the knowledge-base excerpts below",
                      "A clinician must confirm any diagnosis"]
        recommendations = sentences[2:6] or sentences[:4]
        recommendations = recommendations + [
            "Discuss these findings with a licensed physician before acting on them."
        ]
    else:
        summary = (
            f"No AI response could be generated for: \"{shown_query}\". "
            "The language model is not configured or is unreachable, and the "
            "knowledge base returned no matching passage — so this is a system "
            "message, not a medical assessment."
        )
        conditions = [
            "Cannot determine without a working model or matching reference",
            "Professional diagnosis required",
        ]
        recommendations = [
            "Set OPENROUTER_API_KEY or GROQ_API_KEY in your .env file and restart the app.",
            "Check /health for the exact startup error.",
            "Consult a licensed physician or specialist for proper diagnosis.",
            "Do not self-medicate without professional advice.",
        ]

    return {
        "problem_summary": summary,
        "possible_conditions": conditions,
        "severity_level": "moderate",
        "recommendations": recommendations[:5],
        "when_to_seek_help": (
            "Seek immediate medical attention for chest pain, difficulty breathing, "
            "loss of consciousness, severe bleeding, or any rapidly worsening symptoms. "
            + DISCLAIMER
        ),
        "_degraded": degraded,
        "_error": reason or None,
    }


def _default_structured(query: str, context: str = "") -> dict:
    """Backwards-compatible name used by app.py and multimodal_handler.py."""
    return _extractive_structured(query, context, reason="llm unavailable", degraded=True)
