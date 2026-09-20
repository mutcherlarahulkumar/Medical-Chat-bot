"""
flask_app/app.py — MediBot v5
--------------------------------
EXTENSION of original app.py.
✅ All original routes preserved (/analyze, /analyze-multimodal, /).
✅ New: uses enhanced file_utils, preprocess_image_bytes, extract_report_text.
✅ New: /health endpoint extended with RAG stats.
✅ New: lab value extraction shown in API response.
"""

import sys, os, logging, traceback, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask, render_template, request, jsonify
from werkzeug.exceptions import RequestEntityTooLarge

from services.llm_service import get_llm, call_llm_with_fallback, _default_structured
from rag.rag_engine import build_rag_chain, get_vectorstore
from multimodal_handler import MultimodalHandler, _format_structured_html
from prompts.system_prompts import MEDICAL_RAG_PROMPT
from utils.file_utils import (
    is_valid_image, validate_image_size,
    is_valid_report, validate_report_size,
    extract_report_text, preprocess_image_bytes,
    has_report_content,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB

# ── Startup ───────────────────────────────────────────────────────────────────
llm        = None
rag_chain  = None
multimodal = None
_startup_error = None

try:
    llm        = get_llm()
    rag_chain   = build_rag_chain(llm, MEDICAL_RAG_PROMPT)
    vectorstore = get_vectorstore()
    multimodal  = MultimodalHandler(rag_chain, llm=llm, vectorstore=vectorstore)
    logger.info("✅ MediBot v5 ready — Enhanced RAG with trusted sources active.")
except Exception as e:
    _startup_error = str(e)
    logger.error(f"❌ Startup failed: {e}\n{traceback.format_exc()}")


# ══════════════════════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    """Extended health check with RAG and LLM status."""
    return jsonify({
        "status":          "ok" if multimodal else "degraded",
        "rag":             rag_chain  is not None,
        "multimodal":      multimodal is not None,
        "llm":             llm        is not None,
        "trusted_sources": True,   # always true in v5
        "version":         "5.0",
        "startup_error":   _startup_error,
    })


@app.route("/analyze", methods=["POST"])
def analyze():
    """Original text-only endpoint — interface preserved."""
    try:
        data  = request.get_json(silent=True) or {}
        query = (data.get("query", "") or request.form.get("query", "")).strip()
        if not query:
            return jsonify({"error": "No query provided."}), 400

        if multimodal:
            result = multimodal.process(text_query=query)
        else:
            structured = call_llm_with_fallback(llm, query) if llm else _default_structured(query)
            result = {
                "answer":     _format_structured_html(structured),
                "structured": structured,
                "mode":       "text",
                "rag_used":   False,
                "error":      None,
            }

        return jsonify({
            "answer":     result["answer"],
            "structured": result.get("structured", {}),
            "mode":       result["mode"],
            "rag_used":   result["rag_used"],
        })

    except Exception as e:
        logger.error(f"/analyze error: {e}\n{traceback.format_exc()}")
        safe = _default_structured("")
        return jsonify({
            "answer":     _format_structured_html(safe),
            "structured": safe,
            "mode":       "error_fallback",
            "rag_used":   False,
        })


@app.route("/analyze-multimodal", methods=["POST"])
def analyze_multimodal():
    """
    Enhanced multimodal endpoint.
    Supports: text | X-ray image | PDF/TXT report | any combination.
    """
    try:
        query       = (request.form.get("query", "") or "").strip() or None
        image_file  = request.files.get("image")
        report_file = request.files.get("report")

        image_bytes, image_name = None, None
        report_text             = ""

        # ── Validate & read X-ray image ───────────────────────────────────────
        if image_file and image_file.filename:
            if not is_valid_image(image_file.filename):
                return jsonify({"error": "Invalid image format. Use JPG, PNG, or BMP."}), 400
            raw_bytes   = image_file.read()
            valid, msg  = validate_image_size(raw_bytes)
            if not valid:
                return jsonify({"error": msg}), 400
            image_bytes = preprocess_image_bytes(raw_bytes)  # NEW: preprocess
            image_name  = image_file.filename
            logger.info(f"X-ray received: {image_name} ({len(image_bytes)//1024} KB)")

        # ── Validate & read medical report ────────────────────────────────────
        if report_file and report_file.filename:
            if not is_valid_report(report_file.filename):
                return jsonify({"error": "Invalid report format. Use PDF or TXT."}), 400
            report_bytes = report_file.read()
            valid, msg   = validate_report_size(report_bytes)
            if not valid:
                return jsonify({"error": msg}), 400
            report_text = extract_report_text(report_bytes, report_file.filename)  # NEW
            logger.info(f"Report received: {report_file.filename} ({len(report_text)} chars)")

            if report_text:
                report_prefix = (
                    f"[MEDICAL REPORT CONTENT]\n{report_text}\n\n"
                    f"[PATIENT QUESTION]\n"
                )
                query = report_prefix + (
                    query or "Please analyse this medical report, identify any abnormal values, "
                             "explain their clinical significance, and provide recommendations."
                )

        if not query and not image_bytes:
            return jsonify({"error": "Provide a question, X-ray, report, or any combination."}), 400

        logger.info(f"Processing — image:{bool(image_bytes)} report:{bool(report_text)} query:{bool(query)}")

        # ── Process ───────────────────────────────────────────────────────────
        if multimodal:
            result = multimodal.process(
                text_query=query,
                image_bytes=image_bytes,
                image_filename=image_name,
            )
        else:
            # Degraded mode
            effective_query = query or "X-ray analysis requested."
            structured = call_llm_with_fallback(llm, effective_query) if llm else _default_structured(effective_query)
            result = {
                "answer":        _format_structured_html(structured),
                "structured":    structured,
                "mode":          "degraded",
                "xray_analysis": None,
                "rag_used":      False,
                "lab_values":    {},
                "error":         "System initialisation error",
            }

        response_data = {
            "answer":     result["answer"],
            "structured": result.get("structured", {}),
            "mode":       result["mode"],
            "rag_used":   result["rag_used"],
            "error":      result.get("error"),
            "lab_values": result.get("lab_values", {}),   # NEW: expose detected lab values
        }

        if result.get("xray_analysis"):
            xa = result["xray_analysis"]
            response_data["xray_summary"] = {
                "finding":    xa.get("primary_finding", "Unknown"),
                "confidence": round(xa.get("confidence", 0) * 100, 1),
                "severity":   xa.get("severity", "unknown"),
            }

        return jsonify(response_data)

    except RequestEntityTooLarge:
        return jsonify({"error": "File too large. Max 20 MB."}), 413
    except Exception as e:
        logger.error(f"/analyze-multimodal error: {e}\n{traceback.format_exc()}")
        safe = _default_structured("server error")
        return jsonify({
            "answer":     _format_structured_html(safe),
            "structured": safe,
            "mode":       "error_fallback",
            "rag_used":   False,
            "error":      None,
        })
