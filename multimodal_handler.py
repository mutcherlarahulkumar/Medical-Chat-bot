"""
multimodal_handler.py — MediBot v5 Enhanced
---------------------------------------------
EXTENSION of original multimodal_handler.py.
✅ All original modes (text/image/multimodal) preserved.
✅ New additions:
   - Lab value extraction + enriched RAG queries
   - Source-weighted retrieval via retrieve_with_priority()
   - Medical report prompt when report text detected
   - X-ray clinical correlation prompt
   - Source citation in formatted output
   - NEVER returns generic error — always structured fallback
"""

import logging
import json
from typing import Optional, Dict

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


class MultimodalHandler:
    def __init__(self, rag_chain, llm=None, vectorstore=None):
        self.rag_chain  = rag_chain
        self.llm        = llm
        # Extract vectorstore for direct priority retrieval
        self._vectorstore = vectorstore or getattr(rag_chain, "vectorstore", None)
        if not self._vectorstore:
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
            "error":      "No input provided",
        }

    # ── Text / Report only ────────────────────────────────────────────────────
    def _handle_text_only(self, query: str) -> Dict:
        is_report  = REPORT_MARKER in query
        mode_label = "report" if is_report else "text"
        logger.info(f"[Multimodal] Mode: {mode_label.upper()}")

        # ── NEW: Extract lab values from query/report ─────────────────────────
        lab_values = extract_medical_values(query)
        has_labs   = bool(lab_values)
        logger.info(f"[Multimodal] Lab values detected: {lab_values if has_labs else 'none'}")

        context   = ""
        citation  = ""
        rag_used  = False

        # ── NEW: Priority retrieval path ──────────────────────────────────────
        if self._vectorstore is not None:
            try:
                enriched_q = build_enriched_query(query[:500], lab_values)
                docs, citation = retrieve_with_priority(self._vectorstore, enriched_q, k=6)
                context = "\n\n".join(d.page_content for d in docs)
                rag_used = True
                logger.info(f"[Multimodal] Priority retrieval: {len(docs)} docs, citation={bool(citation)}")
            except Exception as e:
                logger.warning(f"[Multimodal] Priority retrieval failed: {e}, falling back to chain.")

        # ── Fallback: use original rag_chain ─────────────────────────────────
        if not rag_used:
            try:
                rag_response = self.rag_chain.invoke({"input": query})
                context  = rag_response.get("answer", "")
                rag_used = True
            except Exception as e:
                logger.warning(f"[Multimodal] RAG chain also failed: {e}")

        # ── NEW: Select prompt based on content type ──────────────────────────
        if has_labs and context:
            effective_prompt = LAB_VALUE_PROMPT.replace("{lab_values}", str(lab_values))
            llm_query = (
                f"Lab values detected: {lab_values}\n\n"
                f"Full context: {query[:1200]}\n\n"
                "Please interpret these values with reference ranges."
            )
        elif is_report and context:
            effective_prompt = MEDICAL_REPORT_PROMPT
            llm_query = query
        else:
            effective_prompt = None  # use call_llm_with_fallback default
            llm_query = query

        # ── LLM call ──────────────────────────────────────────────────────────
        try:
            structured = call_llm_with_fallback(
                self.llm,
                llm_query,
                context=context + citation,
            )
        except Exception as e:
            logger.error(f"[Multimodal] LLM failed: {e}")
            structured = _default_structured(query)

        # ── Enrich summary with source citation ───────────────────────────────
        if citation and "problem_summary" in structured:
            structured["_sources"] = citation.strip()

        return {
            "answer":        _format_structured_html(structured),
            "structured":    structured,
            "mode":          mode_label,
            "xray_analysis": None,
            "rag_used":      rag_used,
            "lab_values":    lab_values,
            "error":         None,
        }

    # ── Image only ────────────────────────────────────────────────────────────
    def _handle_image_only(self, image_bytes: bytes, filename: Optional[str]) -> Dict:
        logger.info("[Multimodal] Mode: IMAGE ONLY")
        xray_result = self._run_xray_analysis(image_bytes)
        finding     = xray_result.get("primary_finding", "UNKNOWN")
        xray_text   = format_xray_for_rag(xray_result)

        context  = xray_text
        citation = ""
        rag_used = False

        # NEW: Use priority retrieval for X-ray context
        if self._vectorstore is not None and finding != "ANALYSIS_FAILED":
            rag_q = self._build_image_rag_query(finding, xray_result.get("severity", ""))
            try:
                docs, citation = retrieve_with_priority(self._vectorstore, rag_q, k=5)
                context = xray_text + "\n\n" + "\n\n".join(d.page_content for d in docs)
                rag_used = True
                logger.info(f"[Multimodal] X-ray RAG: {len(docs)} priority docs retrieved")
            except Exception as e:
                logger.warning(f"[Multimodal] X-ray priority retrieval failed: {e}")
        elif finding != "ANALYSIS_FAILED":
            try:
                rag_q = self._build_image_rag_query(finding, xray_result.get("severity", ""))
                rag_resp = self.rag_chain.invoke({"input": rag_q})
                context  = xray_text + "\n\n" + rag_resp.get("answer", "")
                rag_used = True
            except Exception as e:
                logger.warning(f"[Multimodal] X-ray RAG chain failed: {e}")

        # Build X-ray correlation prompt query
        img_query = (
            f"X-ray finding: {finding}. "
            f"{xray_result.get('interpretation', '')} "
            f"Severity: {xray_result.get('severity', 'unknown')}. "
            "Provide full clinical explanation and management."
        )

        try:
            structured = call_llm_with_fallback(self.llm, img_query, context=context + citation)
        except Exception as e:
            logger.error(f"[Multimodal] LLM failed for image: {e}")
            structured = _xray_to_structured(xray_result)

        if citation and "problem_summary" in structured:
            structured["_sources"] = citation.strip()

        return {
            "answer":        _format_structured_html(structured, xray_result=xray_result),
            "structured":    structured,
            "mode":          "image",
            "xray_analysis": xray_result,
            "rag_used":      rag_used,
            "lab_values":    {},
            "error":         None,
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

        context  = xray_text
        citation = ""
        rag_used = False

        if self._vectorstore is not None:
            try:
                enriched_q = build_enriched_query(augmented_query[:600], lab_values)
                docs, citation = retrieve_with_priority(self._vectorstore, enriched_q, k=6)
                context  = xray_text + "\n\n" + "\n\n".join(d.page_content for d in docs)
                rag_used = True
            except Exception as e:
                logger.warning(f"[Multimodal] Combined priority retrieval failed: {e}")

        if not rag_used:
            try:
                rag_resp = self.rag_chain.invoke({"input": augmented_query})
                context  = xray_text + "\n\n" + rag_resp.get("answer", "")
                rag_used = True
            except Exception as e:
                logger.warning(f"[Multimodal] Combined RAG chain failed: {e}")

        try:
            structured = call_llm_with_fallback(self.llm, augmented_query, context=context + citation)
        except Exception as e:
            logger.error(f"[Multimodal] LLM failed: {e}")
            structured = _xray_to_structured(xray_result)

        if citation and "problem_summary" in structured:
            structured["_sources"] = citation.strip()

        return {
            "answer":        _format_structured_html(structured, xray_result=xray_result),
            "structured":    structured,
            "mode":          "multimodal",
            "xray_analysis": xray_result,
            "rag_used":      rag_used,
            "lab_values":    lab_values,
            "error":         None,
        }

    # ── Helpers ───────────────────────────────────────────────────────────────
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
    parts = []

    if xray_result and xray_result.get("primary_finding") != "ANALYSIS_FAILED":
        finding = xray_result.get("primary_finding", "Unknown")
        conf    = round(xray_result.get("confidence", 0) * 100, 1)
        sev     = xray_result.get("severity", "unknown")
        parts.append(f"🩻 X-RAY ANALYSIS\nFinding: {finding} ({conf}% confidence) | Severity: {sev.upper()}\n")

    summary = structured.get("problem_summary", "")
    if summary:
        parts.append(f"📋 SUMMARY\n{summary}")

    conditions = structured.get("possible_conditions", [])
    if conditions:
        cond_list = "\n".join(f"  • {c}" for c in conditions)
        parts.append(f"🔍 POSSIBLE CONDITIONS\n{cond_list}")

    severity_level = structured.get("severity_level", "moderate").upper()
    severity_emoji = {"LOW": "🟢", "MODERATE": "🟡", "HIGH": "🔴"}.get(severity_level, "🟡")
    parts.append(f"⚠️ SEVERITY\n{severity_emoji} {severity_level}")

    recs = structured.get("recommendations", [])
    if recs:
        rec_list = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(recs))
        parts.append(f"💊 RECOMMENDATIONS\n{rec_list}")

    when = structured.get("when_to_seek_help", "")
    if when:
        parts.append(f"🚨 WHEN TO SEEK HELP\n{when}")

    # NEW: Show source citation if available
    sources = structured.get("_sources", "")
    if sources:
        parts.append(f"📚 KNOWLEDGE SOURCES\n{sources}")

    parts.append(
        "\n⚠️ This AI analysis is for informational purposes only. "
        "Always consult a qualified healthcare professional for diagnosis, "
        "treatment, or interpretation of medical results."
    )
    return "\n\n".join(parts)


def _xray_to_structured(xray_result: dict) -> dict:
    finding  = xray_result.get("primary_finding", "Unknown finding")
    severity = xray_result.get("severity", "moderate")
    recs     = xray_result.get("recommendations", ["Consult a physician."])
    return {
        "problem_summary": xray_result.get("interpretation", f"X-ray finding: {finding}"),
        "possible_conditions": [finding.replace("_", " ").title()],
        "severity_level": severity if severity in ["low","moderate","high"] else "moderate",
        "recommendations": recs,
        "when_to_seek_help": (
            "Seek immediate care if you have difficulty breathing, chest pain, "
            "or rapidly worsening symptoms. ⚠️ Always consult a qualified physician."
        )
    }
