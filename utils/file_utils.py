"""
utils/file_utils.py — MediBot v5
----------------------------------
EXTENSION of original file_utils.py.
✅ Original is_valid_image() and validate_image_size() preserved.
✅ New additions: report validation, image preprocessing, format checks.
"""

import os
import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Original constants ────────────────────────────────────────────────────────
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}
MAX_IMAGE_SIZE_MB         = 20
MAX_IMAGE_SIZE_BYTES      = MAX_IMAGE_SIZE_MB * 1024 * 1024

# ── New constants ─────────────────────────────────────────────────────────────
ALLOWED_REPORT_EXTENSIONS = {".pdf", ".txt", ".doc", ".docx"}
MAX_REPORT_SIZE_MB        = 20
MAX_REPORT_SIZE_BYTES     = MAX_REPORT_SIZE_MB * 1024 * 1024
MAX_REPORT_TEXT_CHARS     = 12000   # increased from 8000 for better report coverage


# ══════════════════════════════════════════════════════════════════════════════
# ORIGINAL FUNCTIONS — preserved exactly
# ══════════════════════════════════════════════════════════════════════════════

def is_valid_image(filename: str) -> bool:
    """Check if the filename has an allowed image extension."""
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_IMAGE_EXTENSIONS


def validate_image_size(image_bytes: bytes):
    """
    Validate image size.
    Returns (True, "") if valid, (False, error_message) if invalid.
    """
    size = len(image_bytes)
    if size > MAX_IMAGE_SIZE_BYTES:
        size_mb = size / (1024 * 1024)
        return False, f"Image too large ({size_mb:.1f} MB). Maximum allowed: {MAX_IMAGE_SIZE_MB} MB."
    if size < 100:
        return False, "Image file appears to be empty or corrupted."
    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
# NEW: Report file validation
# ══════════════════════════════════════════════════════════════════════════════

def is_valid_report(filename: str) -> bool:
    """NEW: Check if filename has an allowed medical report extension."""
    ext = Path(filename).suffix.lower()
    return ext in ALLOWED_REPORT_EXTENSIONS


def validate_report_size(report_bytes: bytes):
    """
    NEW: Validate uploaded report size.
    Returns (True, "") if valid, (False, error_message) if invalid.
    """
    size = len(report_bytes)
    if size > MAX_REPORT_SIZE_BYTES:
        size_mb = size / (1024 * 1024)
        return False, f"Report too large ({size_mb:.1f} MB). Maximum: {MAX_REPORT_SIZE_MB} MB."
    if size < 10:
        return False, "Report file appears to be empty."
    return True, ""


# ══════════════════════════════════════════════════════════════════════════════
# NEW: Enhanced medical report text extraction
# ══════════════════════════════════════════════════════════════════════════════

def extract_report_text(file_bytes: bytes, filename: str) -> str:
    """
    NEW: Extract text from uploaded medical report.
    Supports PDF (via pypdf + pdfplumber fallback) and TXT.
    Returns up to MAX_REPORT_TEXT_CHARS characters.
    Handles encoding errors gracefully.
    """
    ext = Path(filename).suffix.lower()

    # ── Plain text ────────────────────────────────────────────────────────────
    if ext == ".txt":
        try:
            text = file_bytes.decode("utf-8", errors="replace")
            logger.info(f"[FileUtils] TXT: extracted {len(text)} chars")
            return text[:MAX_REPORT_TEXT_CHARS]
        except Exception as e:
            logger.error(f"[FileUtils] TXT decode failed: {e}")
            return ""

    # ── PDF ───────────────────────────────────────────────────────────────────
    if ext == ".pdf":
        text = _extract_pdf_text(file_bytes)
        logger.info(f"[FileUtils] PDF: extracted {len(text)} chars")
        return text[:MAX_REPORT_TEXT_CHARS]

    # ── Fallback: try raw decode ──────────────────────────────────────────────
    try:
        text = file_bytes.decode("utf-8", errors="replace")
        return text[:MAX_REPORT_TEXT_CHARS]
    except Exception:
        return ""


def _extract_pdf_text(file_bytes: bytes) -> str:
    """Try pypdf first, then pdfplumber, then return error string."""
    # Try pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        pages  = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text() or ""
            if page_text.strip():
                pages.append(f"[Page {i+1}]\n{page_text}")
        text = "\n\n".join(pages)
        if text.strip():
            return text
        logger.warning("[FileUtils] pypdf returned empty text, trying pdfplumber...")
    except ImportError:
        logger.warning("[FileUtils] pypdf not installed, trying pdfplumber...")
    except Exception as e:
        logger.warning(f"[FileUtils] pypdf failed: {e}, trying pdfplumber...")

    # Try pdfplumber
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages.append(f"[Page {i+1}]\n{page_text}")
        text = "\n\n".join(pages)
        if text.strip():
            return text
        logger.warning("[FileUtils] pdfplumber also returned empty text (scanned PDF?)")
    except ImportError:
        logger.warning("[FileUtils] pdfplumber not installed. Install: pip install pdfplumber")
    except Exception as e:
        logger.error(f"[FileUtils] pdfplumber failed: {e}")

    return (
        "[PDF text extraction failed. This may be a scanned/image-based PDF. "
        "Please copy-paste the report text into the chat for analysis.]"
    )


# ══════════════════════════════════════════════════════════════════════════════
# NEW: Image preprocessing helper
# ══════════════════════════════════════════════════════════════════════════════

def preprocess_image_bytes(image_bytes: bytes) -> bytes:
    """
    NEW: Preprocesses an uploaded image for X-ray model compatibility.
    - Converts RGBA/P mode to RGB
    - Keeps original bytes if Pillow is unavailable
    Returns processed bytes (JPEG format) or original bytes.
    """
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))

        # Convert palette/RGBA to RGB for model compatibility
        if img.mode in ("RGBA", "P", "L", "LA"):
            img = img.convert("RGB")

        # Resize very large images to max 1024px on longest side
        max_dim = 1024
        w, h = img.size
        if max(w, h) > max_dim:
            scale = max_dim / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
            logger.info(f"[FileUtils] Resized image from {w}x{h} to {img.size}")

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return buf.getvalue()

    except ImportError:
        logger.warning("[FileUtils] Pillow not available for preprocessing.")
        return image_bytes
    except Exception as e:
        logger.warning(f"[FileUtils] Image preprocessing failed: {e}. Using original.")
        return image_bytes


# ══════════════════════════════════════════════════════════════════════════════
# NEW: Utility — detect if query contains medical report content
# ══════════════════════════════════════════════════════════════════════════════

def has_report_content(text: str) -> bool:
    """NEW: Returns True if text appears to contain medical report content."""
    if not text:
        return False
    report_markers = [
        "[MEDICAL REPORT CONTENT]",
        "lab result", "test result", "blood report",
        "mg/dL", "mmol/L", "mEq/L", "U/L", "g/dL",
        "HbA1c", "creatinine", "hemoglobin", "WBC", "RBC",
        "ALT", "AST", "TSH", "troponin", "BNP",
    ]
    text_lower = text.lower()
    return any(m.lower() in text_lower for m in report_markers)
