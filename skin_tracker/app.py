"""
skin_tracker/app.py — Skin Tracker
==================================
A tiny, standalone Flask app that serves a single mobile-friendly page and
proxies "analyse my skin" requests to the Claude API.

Why standalone? The MediBot app pulls in torch / transformers / faiss at import
time. Skin Tracker only needs `flask` + `anthropic`, so it runs on its own:

    python run_skin_tracker.py      # → http://localhost:5001

Photos never touch the server's disk. They live in the browser (IndexedDB) and
are only sent to Claude, in memory, when the user taps "Analyze".

Routes
------
GET  /              — the single-page UI
GET  /health        — reports whether the Claude API key is configured
POST /api/analyze   — {entries: [...]} → Claude → {analysis: "..."}
"""

import base64
import logging
import os
import re

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import RequestEntityTooLarge

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv is optional — env vars may be exported directly
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB of base64 photos

# The user asked for Sonnet 4.6 specifically; override with SKIN_TRACKER_MODEL.
MODEL = os.getenv("SKIN_TRACKER_MODEL", "claude-sonnet-4-6")
MAX_PHOTOS = 4          # today + up to 3 previous
MAX_IMAGE_BYTES = 4 * 1024 * 1024
ALLOWED_MEDIA = {"image/jpeg", "image/png", "image/webp"}

_DATA_URL = re.compile(r"^data:(image/[a-zA-Z+]+);base64,(.+)$", re.DOTALL)

SYSTEM_PROMPT = """You are a friendly skincare progress companion inside a habit-tracking app.

The user photographs their face most days and logs which products they used, in \
the order they applied them. You are shown those photos oldest-first, each \
labelled with its date, time and product log.

Your job is to compare the photos and write a SHORT progress update covering:
  1. Skin texture — smoothness, bumps, flaking, visible pores.
  2. Oiliness — shine across forehead, nose and cheeks.
  3. Breakouts — count, size and location; whether spots are new, healing or gone.
  4. One practical suggestion tied to what they actually logged using.

Rules:
- Keep it under 200 words. Warm, plain language. No clinical jargon.
- Use these four headings exactly: Texture, Oiliness, Breakouts, Suggestion.
- Compare across the photos — say "since Tuesday" or "versus the first photo", \
not just what today looks like.
- Lighting, camera angle and time of day change how skin looks. When a \
difference could be lighting rather than skin, say so.
- If you only receive one photo, say you need a few more days to see a trend, \
and describe the baseline instead.
- You are not a doctor and this is not a diagnosis. If you notice something \
that looks like it needs real medical attention (a mole changing shape or \
colour, a spreading rash, anything painful, bleeding or rapidly growing), say \
plainly that it is worth showing a dermatologist — and do not try to name the \
condition.
- Never comment on attractiveness, weight, age or anything other than skin."""


def _decode_photo(data_url, index):
    """Turn a browser data URL into (media_type, base64_str). Raises ValueError."""
    match = _DATA_URL.match((data_url or "").strip())
    if not match:
        raise ValueError(f"Photo {index + 1} is not a readable image.")

    media_type, payload = match.group(1), match.group(2)
    if media_type not in ALLOWED_MEDIA:
        raise ValueError(f"Photo {index + 1} uses an unsupported format ({media_type}).")

    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception:
        raise ValueError(f"Photo {index + 1} could not be decoded.")

    if not raw:
        raise ValueError(f"Photo {index + 1} is empty.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"Photo {index + 1} is too large — keep each under 4 MB.")

    return media_type, payload


def _label(entry, position, total):
    """Human-readable caption that goes immediately before each image."""
    when = entry.get("label") or entry.get("date") or "unknown date"
    products = [p for p in (entry.get("products") or []) if isinstance(p, str)]
    routine = " → ".join(products) if products else "nothing logged"
    note = (entry.get("note") or "").strip()

    which = "Today's photo" if position == total - 1 else f"Photo {position + 1}"
    line = f"{which} — {when}\nProducts used (in order): {routine}"
    if note:
        line += f"\nTheir note: {note}"
    return line


@app.route("/")
def index():
    return render_template("skin_tracker.html", model=MODEL)


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "model": MODEL,
        "analysis_available": bool(os.getenv("ANTHROPIC_API_KEY")),
    })


@app.route("/api/analyze", methods=["POST"])
def analyze():
    if not os.getenv("ANTHROPIC_API_KEY"):
        return jsonify({
            "error": "No ANTHROPIC_API_KEY set. Add it to your .env file and "
                     "restart the app — everything else works without it."
        }), 503

    try:
        import anthropic
    except ImportError:
        return jsonify({"error": "The `anthropic` package is missing. Run: pip install anthropic"}), 503

    payload = request.get_json(silent=True) or {}
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        return jsonify({"error": "Send at least one entry with a photo."}), 400

    entries = entries[-MAX_PHOTOS:]  # oldest → newest, newest is today

    content = []
    try:
        for i, entry in enumerate(entries):
            media_type, data = _decode_photo(entry.get("photo"), i)
            content.append({"type": "text", "text": _label(entry, i, len(entries))})
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": data},
            })
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    content.append({
        "type": "text",
        "text": "Compare these photos and give me my progress update.",
    })

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=MODEL,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AuthenticationError:
        return jsonify({"error": "Claude rejected the API key. Check ANTHROPIC_API_KEY."}), 502
    except anthropic.RateLimitError:
        return jsonify({"error": "Rate limited by Claude. Wait a moment and try again."}), 429
    except anthropic.APIStatusError as exc:
        logger.error("Claude API error %s: %s", exc.status_code, exc.message)
        return jsonify({"error": f"Claude returned an error ({exc.status_code})."}), 502
    except anthropic.APIConnectionError:
        return jsonify({"error": "Could not reach Claude. Check your connection."}), 502

    if response.stop_reason == "refusal":
        return jsonify({"error": "Claude declined to analyse these photos."}), 422

    text = "\n\n".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        return jsonify({"error": "Claude returned an empty response. Try again."}), 502

    return jsonify({"analysis": text, "model": response.model, "photos": len(entries)})


@app.errorhandler(RequestEntityTooLarge)
def too_large(_):
    return jsonify({"error": "Those photos are too big. Try again with fewer entries."}), 413
