"""
image_model/xray_analyzer.py
----------------------------
Pretrained X-ray analysis using HuggingFace ViT model.
Runs on CPU only. No training required.
Robust error handling — never crashes the server.
"""

import io
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

PRIMARY_MODEL_ID = "nickmuchi/vit-finetuned-chest-xray-pneumonia"
_model_cache: Dict = {}


def _load_model():
    if PRIMARY_MODEL_ID in _model_cache:
        return _model_cache[PRIMARY_MODEL_ID]
    try:
        from transformers import AutoFeatureExtractor, AutoModelForImageClassification
        logger.info(f"[XRay] Downloading model (first run only ~350MB)...")
        extractor = AutoFeatureExtractor.from_pretrained(PRIMARY_MODEL_ID)
        model     = AutoModelForImageClassification.from_pretrained(PRIMARY_MODEL_ID)
        model.eval()
        _model_cache[PRIMARY_MODEL_ID] = (extractor, model)
        logger.info("[XRay] Model loaded successfully.")
        return extractor, model
    except Exception as e:
        logger.error(f"[XRay] Model load failed: {e}")
        raise


def _open_image(image_input):
    from PIL import Image
    if isinstance(image_input, bytes):
        img = Image.open(io.BytesIO(image_input))
    elif isinstance(image_input, (str, Path)):
        img = Image.open(image_input)
    else:
        img = image_input
    return img.convert("RGB")


def analyze_xray(image_input) -> Dict:
    """
    Analyse an X-ray image. Returns a structured dict.
    NEVER raises an exception — always returns a result.
    """
    # Step 1: open image
    try:
        image = _open_image(image_input)
    except Exception as e:
        logger.error(f"[XRay] Cannot open image: {e}")
        return _fallback_result(f"Cannot open image: {e}")

    # Step 2: load model + run inference
    try:
        import torch
        import torch.nn.functional as F

        extractor, model = _load_model()
        with torch.no_grad():
            inputs  = extractor(images=image, return_tensors="pt")
            outputs = model(**inputs)
            probs   = F.softmax(outputs.logits, dim=-1).squeeze().tolist()

        if isinstance(probs, float):
            probs = [probs]

        id2label    = model.config.id2label
        label_probs = {id2label[i]: round(float(p), 4) for i, p in enumerate(probs)}

        top_idx      = max(range(len(probs)), key=lambda i: probs[i])
        primary_label = id2label[top_idx]
        primary_conf  = float(probs[top_idx])

        sorted_findings = sorted(
            [{"label": k, "confidence": v} for k, v in label_probs.items()],
            key=lambda x: x["confidence"], reverse=True
        )

        result = _build_interpretation(primary_label, primary_conf)
        result["all_findings"]      = sorted_findings
        result["raw_probabilities"] = label_probs
        return result

    except ImportError as e:
        msg = f"Missing package: {e}. Please run: pip install transformers torch Pillow"
        logger.error(f"[XRay] {msg}")
        return _fallback_result(msg)
    except Exception as e:
        logger.error(f"[XRay] Inference error: {e}")
        return _fallback_result(str(e))


def _build_interpretation(label: str, confidence: float) -> Dict:
    pct = round(confidence * 100, 1)
    lu  = label.upper()

    if "NORMAL" in lu:
        severity = "normal"
        interp   = (
            f"No significant pathology detected (confidence: {pct}%). "
            "Lung fields appear clear with no obvious consolidation, effusion, or infiltrates. "
            "Cardiac silhouette appears within normal limits."
        )
        recs = [
            "No immediate radiological intervention required.",
            "Routine follow-up as per clinical guidelines.",
            "Correlate with clinical symptoms and lab findings."
        ]
    elif "PNEUMONIA" in lu:
        severity = "moderate" if confidence >= 0.65 else "mild"
        interp   = (
            f"Findings suggest PNEUMONIA (confidence: {pct}%). "
            "Pulmonary infiltrates or consolidation may be present in one or more lung fields."
        )
        recs = [
            "Urgent clinical correlation recommended.",
            "Consider sputum culture and sensitivity.",
            "CBC with differential and CRP/ESR advised.",
            "Antibiotic therapy may be indicated pending culture results.",
            "Monitor oxygen saturation and respiratory rate.",
            "Follow-up X-ray in 4-6 weeks to confirm resolution."
        ]
    elif "EFFUSION" in lu:
        severity = "moderate"
        interp   = (
            f"Findings suggest PLEURAL EFFUSION (confidence: {pct}%). "
            "Fluid accumulation in the pleural space is indicated."
        )
        recs = [
            "Thoracentesis may be required for diagnosis and relief.",
            "Evaluate for heart failure, infection, or malignancy.",
            "Ultrasound-guided aspiration recommended."
        ]
    elif "CARDIOMEGALY" in lu:
        severity = "moderate"
        interp   = (
            f"Findings suggest CARDIOMEGALY (confidence: {pct}%). "
            "Cardiac silhouette appears enlarged beyond normal limits."
        )
        recs = [
            "Echocardiography strongly recommended.",
            "Evaluate for heart failure or cardiomyopathy.",
            "BNP/NT-proBNP blood test advised.",
            "Cardiology referral recommended."
        ]
    else:
        severity = "mild" if confidence < 0.65 else "moderate"
        interp   = (
            f"AI detected: {label} (confidence: {pct}%). "
            "Radiological findings require clinical correlation."
        )
        recs = [
            "Correlate with patient history and symptoms.",
            "Specialist review may be required.",
            "Additional imaging (CT scan) may be warranted."
        ]

    return {
        "primary_finding": label,
        "confidence":      round(confidence, 4),
        "interpretation":  interp,
        "severity":        severity,
        "recommendations": recs,
    }


def _fallback_result(error_msg: str) -> Dict:
    return {
        "primary_finding": "ANALYSIS_FAILED",
        "confidence":       0.0,
        "all_findings":     [],
        "interpretation":   (
            "X-ray analysis could not be completed. "
            f"Reason: {error_msg}"
        ),
        "severity":         "unknown",
        "recommendations": [
            "Ensure transformers and torch are installed: pip install transformers torch Pillow",
            "Re-upload a clear chest X-ray in JPG or PNG format.",
            "Consult a radiologist for manual review."
        ],
        "raw_probabilities": {}
    }


def format_xray_for_rag(analysis_result: Dict) -> str:
    """Convert X-ray analysis dict into a text string for the RAG pipeline."""
    finding  = analysis_result.get("primary_finding", "Unknown")
    conf     = round(analysis_result.get("confidence", 0) * 100, 1)
    interp   = analysis_result.get("interpretation", "")
    severity = analysis_result.get("severity", "unknown").upper()
    recs     = analysis_result.get("recommendations", [])
    rec_text = "\n".join(f"  - {r}" for r in recs)

    return f"""
=== X-RAY IMAGE ANALYSIS REPORT ===
Primary Finding   : {finding}
Confidence        : {conf}%
Severity Level    : {severity}

Radiological Interpretation:
{interp}

Clinical Recommendations:
{rec_text}
====================================
"""
