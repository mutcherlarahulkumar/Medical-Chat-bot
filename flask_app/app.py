"""
flask_app/app.py — MediBot
--------------------------------
Routes: /  /analyze  /analyze-multimodal  /health

Fixes in this revision
----------------------
* Startup no longer dies when no API key is set. The vector store is built
  independently of the LLM, so the app can still answer from the knowledge
  base. Previously a missing key killed `multimodal`, and every single request
  fell through to one hard-coded paragraph — which is why every input produced
  the same output.
* Responses carry `degraded` + `error` so the UI can say the model did not
  answer instead of presenting a system message as a medical answer.
* /health reports the real state of each subsystem.
"""

import sys, os, logging, traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from flask import Flask, render_template, request, jsonify
from werkzeug.exceptions import RequestEntityTooLarge

from services.llm_service import try_get_llm, _default_structured
from rag.rag_engine import build_rag_chain, get_vectorstore
from multimodal_handler import MultimodalHandler, _format_structured_html
from prompts.system_prompts import MEDICAL_RAG_PROMPT
from utils.file_utils import (
    is_valid_image, validate_image_size,
    is_valid_report, validate_report_size,
    extract_report_text, preprocess_image_bytes,
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
llm          = None
rag_chain    = None
vectorstore  = None
multimodal   = None
_llm_error   = None
_rag_error   = None

# 1. LLM — non-fatal. Without it we still serve knowledge-base answers.
llm, _llm_error = try_get_llm()
if _llm_error:
    logger.error(f"⚠️  LLM unavailable: {_llm_error}")

# 2. Vector store — independent of the LLM.
try:
    vectorstore = get_vectorstore()
    logger.info("✅ Vector store loaded.")
except Exception as e:
    _rag_error = str(e)
    logger.error(f"❌ Vector store failed to load: {e}\n{traceback.format_exc()}")

# 3. RAG chain — only possible with both.
if llm is not None and vectorstore is not None:
    try:
        rag_chain = build_rag_chain(llm, MEDICAL_RAG_PROMPT)
    except Exception as e:
        _rag_error = (_rag_error or "") + f" | rag_chain: {e}"
        logger.error(f"❌ RAG chain failed: {e}")

# 4. Handler — works with whatever is available.
multimodal = MultimodalHandler(rag_chain, llm=llm, vectorstore=vectorstore)

if llm is not None and vectorstore is not None:
    logger.info("✅ MediBot ready — LLM + enhanced RAG with trusted sources active.")
elif vectorstore is not None:
    logger.warning("⚠️  MediBot running in KNOWLEDGE-BASE-ONLY mode (no LLM configured).")
else:
    logger.warning("⚠️  MediBot running DEGRADED — no LLM and no vector index.")


def _startup_summary() -> str:
    problems = []
    if llm is None:
        problems.append("No AI model configured — set OPENROUTER_API_KEY or GROQ_API_KEY in .env.")
    if vectorstore is None:
        problems.append("Medical knowledge index not loaded — run: python build_index.py --force")
    return " ".join(problems)


# ══════════════════════════════════════════════════════════════════════════════
# Routes
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    """Health check reporting the real state of each subsystem."""
    if llm is not None and vectorstore is not None:
        status = "ok"
    elif vectorstore is not None or llm is not None:
        status = "degraded"
    else:
        status = "down"

    return jsonify({
        "status":          status,
        "llm":             llm is not None,
        "llm_error":       _llm_error or None,
        "rag":             vectorstore is not None,
        "rag_chain":       rag_chain is not None,
        "rag_error":       _rag_error or None,
        "multimodal":      multimodal is not None,
        "trusted_sources": vectorstore is not None,
        "version":         "5.0",
        "message":         _startup_summary() or "All subsystems operational.",
    })


def _response_payload(result: dict) -> dict:
    payload = {
        "answer":     result.get("answer", ""),
        "structured": result.get("structured", {}),
        "mode":       result.get("mode", "text"),
        "rag_used":   result.get("rag_used", False),
        "degraded":   bool(result.get("degraded")),
        "error":      result.get("error"),
        "lab_values": result.get("lab_values", {}),
        "llm_online": llm is not None,
    }
    if payload["degraded"] and not payload["error"]:
        payload["error"] = _startup_summary() or "The AI model did not return an answer."

    xa = result.get("xray_analysis")
    if xa:
        payload["xray_summary"] = {
            "finding":    xa.get("primary_finding", "Unknown"),
            "confidence": round(xa.get("confidence", 0) * 100, 1),
            "severity":   xa.get("severity", "unknown"),
        }
    return payload


@app.route("/analyze", methods=["POST"])
def analyze():
    """Text-only endpoint — interface preserved."""
    try:
        data  = request.get_json(silent=True) or {}
        query = (data.get("query", "") or request.form.get("query", "")).strip()
        if not query:
            return jsonify({"error": "No query provided."}), 400

        result = multimodal.process(text_query=query)
        return jsonify(_response_payload(result))

    except Exception as e:
        logger.error(f"/analyze error: {e}\n{traceback.format_exc()}")
        safe = _default_structured("")
        return jsonify({
            "answer":     _format_structured_html(safe),
            "structured": safe,
            "mode":       "error_fallback",
            "rag_used":   False,
            "degraded":   True,
            "error":      f"Server error: {e}",
            "lab_values": {},
            "llm_online": llm is not None,
        }), 500


@app.route("/analyze-multimodal", methods=["POST"])
def analyze_multimodal():
    """
    Multimodal endpoint.
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
            image_bytes = preprocess_image_bytes(raw_bytes)
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
            report_text = extract_report_text(report_bytes, report_file.filename)
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

        result = multimodal.process(
            text_query=query,
            image_bytes=image_bytes,
            image_filename=image_name,
        )
        return jsonify(_response_payload(result))

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
            "degraded":   True,
            "error":      f"Server error: {e}",
            "lab_values": {},
            "llm_online": llm is not None,
        }), 500
