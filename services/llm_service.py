"""
services/llm_service.py
------------------------
LLM factory — supports OpenRouter (primary) + Groq (fallback).
Fallback chain: OpenRouter → Groq → safe offline structured response.
"""

import os
import json
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


def get_llm():
    """
    Return the appropriate LLM. Priority: OpenRouter → Groq → RuntimeError.
    """
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if openrouter_key and not openrouter_key.startswith("your_"):
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
                default_headers={
                    "HTTP-Referer": "http://localhost:5000",
                    "X-Title": "MediBot Medical Assistant",
                },
            )
        except Exception as e:
            logger.error(f"[LLM] OpenRouter init failed: {e}")

    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if groq_key and not groq_key.startswith("your_"):
        model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        logger.info(f"[LLM] Using Groq: {model}")
        try:
            from langchain_groq import ChatGroq
            return ChatGroq(model=model, api_key=groq_key, temperature=0.3, max_tokens=1024)
        except Exception as e:
            logger.error(f"[LLM] Groq init failed: {e}")

    raise RuntimeError(
        "No LLM configured! Set one of these in your .env:\n"
        "  OPENROUTER_API_KEY=sk-or-v1-...  (free: https://openrouter.ai/keys)\n"
        "  GROQ_API_KEY=gsk_...             (free: https://console.groq.com)"
    )


def call_llm_with_fallback(llm, prompt: str, context: str = "") -> dict:
    """
    Call LLM and always return structured JSON dict. Never raises.
    """
    structured_prompt = f"""You are an expert medical assistant. Analyze the following and respond ONLY with valid JSON (no markdown fences, no extra text).

{f'Medical context from knowledge base: {context}' if context else ''}

User query: {prompt}

Required JSON format (use exactly these keys):
{{
  "problem_summary": "1-2 sentence summary of the medical concern",
  "possible_conditions": ["Condition 1", "Condition 2", "Condition 3"],
  "severity_level": "low",
  "recommendations": ["Step 1", "Step 2", "Step 3"],
  "when_to_seek_help": "Describe specific warning signs requiring immediate care"
}}

Rules:
- severity_level must be exactly: low, moderate, or high
- possible_conditions: 2-4 items
- recommendations: 3-5 specific, actionable steps
- Never fabricate drug dosages or specific prescriptions"""

    def _parse_llm_response(text):
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                if "{" in part:
                    text = part.lstrip("json").strip()
                    break
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
        return json.loads(text)

    # Try primary LLM
    try:
        from langchain_core.messages import HumanMessage
        response = llm.invoke([HumanMessage(content=structured_prompt)])
        result = _parse_llm_response(response.content)
        for k in ["problem_summary", "possible_conditions", "severity_level",
                   "recommendations", "when_to_seek_help"]:
            if k not in result:
                result[k] = _default_structured(prompt)[k]
        logger.info("[LLM] Primary LLM call succeeded.")
        return result
    except Exception as e:
        logger.warning(f"[LLM] Primary LLM call failed: {e}. Trying Groq fallback...")

    # Groq fallback
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if groq_key and not groq_key.startswith("your_"):
        try:
            from langchain_groq import ChatGroq
            from langchain_core.messages import HumanMessage
            fallback = ChatGroq(model="llama-3.3-70b-versatile", api_key=groq_key,
                                temperature=0.3, max_tokens=512)
            response = fallback.invoke([HumanMessage(content=structured_prompt)])
            result = _parse_llm_response(response.content)
            logger.info("[LLM] Groq fallback succeeded.")
            return result
        except Exception as fe:
            logger.error(f"[LLM] Groq fallback failed: {fe}")

    logger.warning("[LLM] All providers failed. Returning safe offline response.")
    return _default_structured(prompt)


def _default_structured(query: str) -> dict:
    return {
        "problem_summary": (
            f"Unable to generate a live AI response for: '{query[:100]}'. "
            "Based on your query, please consult a healthcare professional for accurate diagnosis."
        ),
        "possible_conditions": [
            "Cannot determine without medical examination",
            "Professional diagnosis required"
        ],
        "severity_level": "moderate",
        "recommendations": [
            "Consult a licensed physician or specialist for proper diagnosis.",
            "Do not self-medicate without professional advice.",
            "If symptoms are severe or worsening, seek emergency care immediately.",
            "Keep a record of your symptoms including onset, duration, and severity."
        ],
        "when_to_seek_help": (
            "Seek immediate medical attention if you experience chest pain, difficulty breathing, "
            "loss of consciousness, severe bleeding, or any rapidly worsening symptoms."
        )
    }
