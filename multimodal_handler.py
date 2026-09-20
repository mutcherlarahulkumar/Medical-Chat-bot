"""
multimodal_handler.py — MediBot
---------------------------------------------
Routes a request (text / X-ray / report / combined) to the right prompt,
retrieves supporting context, and returns a structured answer.

Fixes in this revision
----------------------
* The mode-specific prompt is now actually passed to the LLM. `effective_prompt`
  used to be computed and then thrown away, so report mode, lab mode and plain
  chat all sent the same hard-coded prompt and came back with the same shape of
  answer regardless of input.
* The RAG-chain fallback now feeds the *retrieved documents* to the LLM as
  context. It used to feed the chain's own JSON answer back in as "context",
  which collapsed two different questions into near-identical output.
* The lab-value path keeps the user's real question instead of replacing it
  with a fixed sentence.
* Works with llm=None (knowledge-base-only mode) instead of erroring.
* `degraded` / `error` are propagated so the caller can tell the user the model
  did not answer.
"""

import logging
from typing import Optional, Dict, List

from image_model.xray_analyzer import analyze_xray, format_xray_for_rag
from services.llm_service import call_llm_with_fallback, _default_structured
from rag.rag_engine import (
    retrieve_with_priority,
    extract_medical_values,
    build_enriched_query,
)
from prompts.system_prompts import (
    MEDICAL_RAG_PROMPT,
    MEDICAL_REPORT_PROMPT,
    LAB_VALUE_PROMPT,
    XRAY_CORRELATION_PROMPT,
)

logger = logging.getLogger(__name__)

# Detect medical report text prefix added by app.py
REPORT_MARKER = "[MEDICAL REPORT CONTENT]"

# Cap the context handed to the model — an over-long context makes free-tier
# models truncate their JSON, which then fails to parse and drops the request
# into the canned fallback.
MAX_CONTEXT_CHARS = 6000


class MultimodalHandler:
    def __init__(self, rag_chain, llm=None, vectorstore=None):
        self.rag_chain  = rag_chain
        self.llm        = llm
        # Extract vectorstore for direct priority retrieval
        self._vectorstore = vectorstore or getattr(rag_chain, "vectorstore", None)
        if not self._vectorstore and rag_chain is not None:
            try:
                # LangChain chain → retriever → vectorstore
                self._vectorstore = rag_chain.retriever.vectorstore
            except Exception:
                try:
                    self._vectorstore = rag_chain.steps[0].vectorstore
                except Exception:
                    logger.warning("[Multimodal] Could not extract vectorstore — using chain retrieval.")

    # ── Public entry point ────────────────────────────────────────────────────
    def process(
        self,
        text_query: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        image_filename: Optional[str] = None,
    ) -> Dict:
        has_text  = bool(text_query and text_query.strip())
        has_image = bool(image_bytes)

        if has_text and not has_image:
            return self._handle_text_only(text_query)
        if has_image and not has_text:
            return self._handle_image_only(image_bytes, image_filename)
        if has_text and has_image:
            return self._handle_multimodal(text_query, image_bytes, image_filename)

        return {
            "answer":     "Please provide a question, an X-ray image, a medical report, or both.",
            "structured": _default_structured("empty input"),
            "mode":       "empty",
            "xray_analysis": None,
            "rag_used":   False,
            "degraded":   False,
            "error":      "No input provided",
        }

    # ── Retrieval (shared by all three modes) ─────────────────────────────────
    def _retrieve(self, query: str, k: int = 6, lab_values: Optional[Dict] = None):
        """
        Returns (context_text, citation, rag_used).
        Tries priority retrieval first, then the plain RAG chain's retriever.
        """
        if self._vectorstore is not None:
            try:
                enriched_q = build_enriched_query(query[:600], lab_values or {})
                docs, citation = retrieve_with_priority(self._vectorstore, enriched_q, k=k)
                if docs:
                    return self._join_docs(docs), citation, True
                logger.info("[Multimodal] Priority retrieval returned no documents.")
            except Exception as e:
                logger.warning(f"[Multimodal] Priority retrieval failed: {e}, falling back to chain.")

        if self.rag_chain is not None:
            try:
                rag_response = self.rag_chain.invoke({"input": query})
                # Use the retrieved DOCUMENTS as context, not the chain's answer.
                docs = rag_response.get("context") or []
                if docs:
                    return self._join_docs(docs), "", True
                logger.info("[Multimodal] RAG chain returned no context documents.")
            except Exception as e:
                logger.warning(f"[Multimodal] RAG chain also failed: {e}")

        return "", "", False

    @staticmethod
    def _join_docs(docs: List) -> str:
        parts, total = [], 0
        for doc in docs:
            content = getattr(doc, "page_content", str(doc)).strip()
            if not content:
                continue
            if total + len(content) > MAX_CONTEXT_CHARS:
                parts.append(content[: max(0, MAX_CONTEXT_CHARS - total)])
                break
            parts.append(content)
            total += len(content)
        return "\n\n---\n\n".join(parts)

    # ── Text / Report only ────────────────────────────────────────────────────
    def _handle_text_only(self, query: str) -> Dict:
        is_report  = REPORT_MARKER in query
        mode_label = "report" if is_report else "text"
        logger.info(f"[Multimodal] Mode: {mode_label.upper()}")

        lab_values = extract_medical_values(query)
        has_labs   = bool(lab_values)
        logger.info(f"[Multimodal] Lab values detected: {lab_values if has_labs else 'none'}")

        context, citation, rag_used = self._retrieve(query, k=6, lab_values=lab_values)

        # ── Select the prompt for this content type and USE it ────────────────
        # Order matters: a full report gets the report prompt even when it also
        # contains lab values, because that prompt reads values as a pattern
        # rather than one at a time. The detected values are still handed over.
        prompt_fields = {}
        formatted_labs = ", ".join(f"{k.replace('_', ' ')}={v}" for k, v in lab_values.items())

        if is_report:
            effective_prompt = MEDICAL_REPORT_PROMPT
            mode_label = "report"
            if formatted_labs:
                context += f"\n\nAUTO-DETECTED VALUES IN THIS REPORT: {formatted_labs}"
        elif has_labs:
            effective_prompt = LAB_VALUE_PROMPT
            prompt_fields["lab_values"] = formatted_labs
            mode_label = "lab_values"
        else:
            effective_prompt = MEDICAL_RAG_PROMPT
            mode_label = "text"

        structured = self._call_llm(
            query, context + citation, effective_prompt, prompt_fields
        )

        if citation:
            structured["_sources"] = citation.strip()

        return {
            "answer":        _format_structured_html(structured),
            "structured":    structured,
            "mode":          mode_label,
            "xray_analysis": None,
            "rag_used":      rag_used,
            "lab_values":    lab_values,
            "degraded":      bool(structured.get("_degraded")),
            "error":         structured.get("_error"),
        }

    # ── Image only ────────────────────────────────────────────────────────────
    def _handle_image_only(self, image_bytes: bytes, filename: Optional[str]) -> Dict:
        logger.info("[Multimodal] Mode: IMAGE ONLY")
        xray_result = self._run_xray_analysis(image_bytes)
        finding     = xray_result.get("primary_finding", "UNKNOWN")
        xray_text   = format_xray_for_rag(xray_result)

        context, citation, rag_used = "", "", False
        if finding != "ANALYSIS_FAILED":
            rag_q = self._build_image_rag_query(finding, xray_result.get("severity", ""))
            context, citation, rag_used = self._retrieve(rag_q, k=5)

        full_context = (xray_text + "\n\n" + context).strip() if context else xray_text

        img_query = (
            f"An X-ray was analysed and the finding is: {finding}. "
            f"{xray_result.get('interpretation', '')} "
            f"Explain what this means clinically, the likely symptoms, the recommended "
            f"work-up, and how it is usually managed."
        )

        structured = self._call_llm(
            img_query, full_context + citation, XRAY_CORRELATION_PROMPT,
            {
                "xray_finding": finding,
                "confidence":   round(xray_result.get("confidence", 0) * 100, 1),
                "severity":     xray_result.get("severity", "unknown"),
            },
            xray_fallback=xray_result,
        )

        if citation:
            structured["_sources"] = citation.strip()

        return {
            "answer":        _format_structured_html(structured, xray_result=xray_result),
            "structured":    structured,
            "mode":          "image",
            "xray_analysis": xray_result,
            "rag_used":      rag_used,
            "lab_values":    {},
            "degraded":      bool(structured.get("_degraded")),
            "error":         structured.get("_error"),
        }

    # ── Text + Image ──────────────────────────────────────────────────────────
    def _handle_multimodal(self, query: str, image_bytes: bytes, filename: Optional[str]) -> Dict:
        logger.info("[Multimodal] Mode: TEXT + IMAGE")
        xray_result = self._run_xray_analysis(image_bytes)
        xray_text   = format_xray_for_rag(xray_result)
        finding     = xray_result.get("primary_finding", "UNKNOWN")

        lab_values = extract_medical_values(query)

        augmented_query = (
            f"X-ray finding: {finding}. {xray_result.get('interpretation', '')}\n\n"
            f"Patient question: {query}"
        )

        context, citation, rag_used = self._retrieve(augmented_query, k=6, lab_values=lab_values)
        full_context = (xray_text + "\n\n" + context).strip() if context else xray_text

        structured = self._call_llm(
            augmented_query, full_context + citation, XRAY_CORRELATION_PROMPT,
            {
                "xray_finding": finding,
                "confidence":   round(xray_result.get("confidence", 0) * 100, 1),
                "severity":     xray_result.get("severity", "unknown"),
            },
            xray_fallback=xray_result,
        )

        if citation:
            structured["_sources"] = citation.strip()

        return {
            "answer":        _format_structured_html(structured, xray_result=xray_result),
            "structured":    structured,
            "mode":          "multimodal",
            "xray_analysis": xray_result,
            "rag_used":      rag_used,
            "lab_values":    lab_values,
            "degraded":      bool(structured.get("_degraded")),
            "error":         structured.get("_error"),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _call_llm(self, query: str, context: str, system_prompt: str,
                  prompt_fields: Dict, xray_fallback: Optional[Dict] = None) -> Dict:
        try:
            return call_llm_with_fallback(
                self.llm, query,
                context=context,
                system_prompt=system_prompt,
                prompt_fields=prompt_fields,
            )
        except Exception as e:
            logger.error(f"[Multimodal] LLM call raised: {e}")
            if xray_fallback:
                return _xray_to_structured(xray_fallback, error=str(e))
            return _default_structured(query, context)

    def _run_xray_analysis(self, image_bytes: bytes) -> Dict:
        try:
            result = analyze_xray(image_bytes)
            logger.info(f"[Multimodal] X-ray: {result.get('primary_finding')} "
                        f"({result.get('confidence', 0)*100:.1f}%)")
            return result
        except Exception as e:
            logger.error(f"[Multimodal] X-ray analysis failed: {e}")
            return {
                "primary_finding": "ANALYSIS_FAILED",
                "confidence": 0.0,
                "interpretation": f"Image analysis error: {e}",
                "severity": "unknown",
                "recommendations": ["Please consult a radiologist."],
                "raw_probabilities": {}
            }

    def _build_image_rag_query(self, finding: str, severity: str) -> str:
        queries = {
            "PNEUMONIA":     "pneumonia symptoms causes diagnosis treatment antibiotics complications management",
            "NORMAL":        "normal chest X-ray findings lung health preventive care respiratory",
            "EFFUSION":      "pleural effusion causes diagnosis treatment thoracentesis management",
            "CARDIOMEGALY":  "cardiomegaly enlarged heart causes heart failure diagnosis echocardiogram treatment",
            "ATELECTASIS":   "atelectasis lung collapse causes symptoms diagnosis treatment management",
            "TUBERCULOSIS":  "tuberculosis TB chest X-ray diagnosis treatment RNTCP guidelines",
            "MASS":          "lung mass pulmonary nodule chest X-ray differential diagnosis evaluation CT",
            "CONSOLIDATION": "pulmonary consolidation causes diagnosis differential pneumonia treatment",
        }
        for key, query in queries.items():
            if key in finding.upper():
                return query
        finding_clean = finding.replace("_", " ").title()
        return f"{finding_clean} clinical presentation diagnosis treatment management guidelines"


# ══════════════════════════════════════════════════════════════════════════════
# Formatting helpers
# ══════════════════════════════════════════════════════════════════════════════

def _format_structured_html(structured: dict, xray_result: dict = None) -> str:
    """
    Plain-text rendering of the structured answer.

    The browser UI renders the `structured` dict itself so it can style each
    section; this text version is kept for API clients and for the transcript
    fallback when `structured` is missing.
    """
    parts = []

    if structured.get("_degraded"):
        parts.append(
            "⚠️ SERVICE NOTICE\nThe AI model did not return an answer for this "
            "request, so the text below is a system message rather than a "
            "medical assessment."
        )

    if xray_result and xray_result.get("primary_finding") != "ANALYSIS_FAILED":
        finding = xray_result.get("primary_finding", "Unknown")
        conf    = round(xray_result.get("confidence", 0) * 100, 1)
        sev     = xray_result.get("severity", "unknown")
        parts.append(f"🩻 X-RAY ANALYSIS\nFinding: {finding} ({conf}% confidence) | Severity: {sev.upper()}")

    summary = structured.get("problem_summary", "")
    if summary:
        parts.append(f"📋 SUMMARY\n{summary}")

    conditions = structured.get("possible_conditions", [])
    if conditions:
        cond_list = "\n".join(f"  • {c}" for c in conditions)
        parts.append(f"🔍 POSSIBLE CONDITIONS\n{cond_list}")

    severity_level = str(structured.get("severity_level", "moderate")).upper()
    severity_emoji = {"LOW": "🟢", "MODERATE": "🟡", "HIGH": "🔴"}.get(severity_level, "🟡")
    parts.append(f"⚠️ SEVERITY\n{severity_emoji} {severity_level}")

    recs = structured.get("recommendations", [])
    if recs:
        rec_list = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(recs))
        parts.append(f"💊 RECOMMENDATIONS\n{rec_list}")

    when = structured.get("when_to_seek_help", "")
    if when:
        parts.append(f"🚨 WHEN TO SEEK HELP\n{when}")

    sources = structured.get("_sources", "")
    if sources:
        parts.append(f"📚 KNOWLEDGE SOURCES\n{sources}")

    parts.append(
        "⚠️ This AI analysis is for informational purposes only. "
        "Always consult a qualified healthcare professional for diagnosis, "
        "treatment, or interpretation of medical results."
    )
    return "\n\n".join(parts)


def _xray_to_structured(xray_result: dict, error: str = None) -> dict:
    finding  = xray_result.get("primary_finding", "Unknown finding")
    severity = xray_result.get("severity", "moderate")
    recs     = xray_result.get("recommendations", ["Consult a physician."])
    return {
        "problem_summary": xray_result.get("interpretation", f"X-ray finding: {finding}"),
        "possible_conditions": [finding.replace("_", " ").title()],
        "severity_level": severity if severity in ["low", "moderate", "high"] else "moderate",
        "recommendations": recs,
        "when_to_seek_help": (
            "Seek immediate care if you have difficulty breathing, chest pain, "
            "or rapidly worsening symptoms. ⚠️ Always consult a qualified physician."
        ),
        "_degraded": True,
        "_error": error,
    }
