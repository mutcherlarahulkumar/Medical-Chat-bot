"""
skin_tracker/app.py — Skin Tracker
==================================
A standalone Flask app: a single mobile-first page (installable on Android as a
PWA) backed by server-side storage, with an "Analyze" button that asks Claude
to compare your recent face photos.

    python run_skin_tracker.py      # → http://localhost:5001

Photos are stored on this server (skin_tracker/data/), not in the browser, so
your phone and laptop see the same timeline. They are sent to Anthropic only
when you tap Analyze.

Routes
------
GET    /                   the app shell
GET    /manifest.webmanifest, /sw.js, /icon-<n>.png   PWA plumbing
GET    /health             config + storage status
GET    /api/entries        newest-first list (metadata only)
POST   /api/entries        {photo, products, note} → new entry
DELETE /api/entries/<id>   remove an entry and its photo
GET    /api/photo/<id>     the JPEG itself
GET    /api/routine        product list, in application order
PUT    /api/routine        replace the product list
POST   /api/analyze        compare the latest entries via Claude
"""

import base64
import logging
import os
import struct
import time
import zlib

from flask import Flask, Response, jsonify, render_template, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from skin_tracker import store

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # optional — env vars may be exported directly
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024   # one photo per request now

MODEL = os.getenv("SKIN_TRACKER_MODEL", "claude-sonnet-4-6")
MAX_PHOTOS = 4          # today + up to 3 previous

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


# ── the page + PWA plumbing ──────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("skin_tracker.html", model=MODEL)


@app.route("/manifest.webmanifest")
def manifest():
    return jsonify({
        "name": "Skin Tracker",
        "short_name": "Skin",
        "description": "Daily skin photos, your routine, and progress checks.",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#fff5f8",
        "theme_color": "#ffeaf1",
        "icons": [
            {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable"},
            {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    })


@app.route("/sw.js")
def service_worker():
    """Cache the shell so the app opens instantly and works offline.

    Photos and entries are deliberately NOT cached — they're the live data.
    """
    js = """
const SHELL = "skin-tracker-shell-v1";
const ASSETS = ["/", "/manifest.webmanifest", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(SHELL).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== SHELL).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  if (url.pathname.startsWith("/api/")) return;          // always live
  e.respondWith(
    fetch(e.request)
      .then(res => {
        const copy = res.clone();
        caches.open(SHELL).then(c => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request).then(hit => hit || caches.match("/")))
  );
});
"""
    return Response(js, mimetype="application/javascript")


def _png(size):
    """A flat pink rounded-square icon, generated so no binary assets are vendored."""
    r, g, b = 0xE0, 0x5C, 0x86
    bg = (0xFF, 0xEA, 0xF1)
    radius = size // 5
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # PNG filter byte: none
        for x in range(size):
            # rounded-corner mask
            dx = min(x, size - 1 - x)
            dy = min(y, size - 1 - y)
            outside = (dx < radius and dy < radius and
                       (radius - dx) ** 2 + (radius - dy) ** 2 > radius ** 2)
            # a simple blossom: filled circle in the middle
            cx = cy = (size - 1) / 2
            inner = (x - cx) ** 2 + (y - cy) ** 2 <= (size * 0.27) ** 2
            if outside:
                rows += bytes(bg)
            elif inner:
                rows += bytes((0xFF, 0xFF, 0xFF))
            else:
                rows += bytes((r, g, b))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)  # 8-bit RGB
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
            + chunk(b"IEND", b""))


@app.route("/icon-<int:size>.png")
def icon(size):
    if size not in (192, 512):
        return jsonify({"error": "no such icon"}), 404
    return Response(_png(size), mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=604800"})


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "model": MODEL,
        "analysis_available": bool(os.getenv("ANTHROPIC_API_KEY")),
        "storage": "server",
        **store.stats(),
    })


# ── entries ──────────────────────────────────────────────────────────────────
@app.route("/api/entries", methods=["GET"])
def list_entries():
    return jsonify({"entries": store.list_entries()})


@app.route("/api/entries", methods=["POST"])
def create_entry():
    body = request.get_json(silent=True) or {}
    try:
        entry = store.add_entry(
            body.get("photo"),
            body.get("products"),
            body.get("note"),
            ts=int(time.time() * 1000),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except OSError as exc:
        logger.error("Could not write photo: %s", exc)
        return jsonify({"error": "The server couldn't save that photo to disk."}), 500
    return jsonify({"entry": entry}), 201


@app.route("/api/entries/<int:entry_id>", methods=["DELETE"])
def remove_entry(entry_id):
    if not store.delete_entry(entry_id):
        return jsonify({"error": "That entry no longer exists."}), 404
    return jsonify({"deleted": entry_id})


@app.route("/api/photo/<int:entry_id>")
def photo(entry_id):
    path = store.photo_path(entry_id)
    if not path:
        return jsonify({"error": "No photo for that entry."}), 404
    return send_file(path, max_age=31536000, conditional=True)


# ── routine ──────────────────────────────────────────────────────────────────
@app.route("/api/routine", methods=["GET"])
def get_routine():
    return jsonify({"products": store.get_routine()})


@app.route("/api/routine", methods=["PUT"])
def put_routine():
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("products"), list):
        return jsonify({"error": "Send {\"products\": [...]}"}), 400
    try:
        return jsonify({"products": store.set_routine(body["products"])})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


# ── the Claude call ──────────────────────────────────────────────────────────
def _label(entry, position, total):
    when = entry.get("label") or "unknown date"
    routine = " → ".join(entry["products"]) if entry["products"] else "nothing logged"
    which = "Today's photo" if position == total - 1 else f"Photo {position + 1}"
    line = f"{which} — {when}\nProducts used (in order): {routine}"
    if entry.get("note"):
        line += f"\nTheir note: {entry['note']}"
    return line


@app.route("/api/analyze", methods=["POST"])
def analyze():
    if not os.getenv("ANTHROPIC_API_KEY"):
        return jsonify({
            "error": "No ANTHROPIC_API_KEY set. Add it to .env and restart — "
                     "tracking works fine without it."
        }), 503
    try:
        import anthropic
    except ImportError:
        return jsonify({"error": "The `anthropic` package is missing. Run: pip install anthropic"}), 503

    # Photos already live on this server — the client just says "go".
    entries = store.list_entries(limit=MAX_PHOTOS)
    if not entries:
        return jsonify({"error": "Save a photo first."}), 400
    entries = list(reversed(entries))              # oldest → newest

    labels = (request.get_json(silent=True) or {}).get("labels") or {}

    content = []
    for i, entry in enumerate(entries):
        path = store.photo_path(entry["id"])
        if not path:
            logger.warning("Entry %s has no photo on disk — skipping.", entry["id"])
            continue
        with open(path, "rb") as fh:
            raw = fh.read()
        labelled = dict(entry, label=labels.get(str(entry["id"])))
        content.append({"type": "text", "text": _label(labelled, i, len(entries))})
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": _media_type(path),
                "data": base64.standard_b64encode(raw).decode("ascii"),
            },
        })

    if not content:
        return jsonify({"error": "Your entries have no readable photos."}), 400
    content.append({"type": "text", "text": "Compare these photos and give me my progress update."})

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
        return jsonify({"error": "Claude rejected the API key. Check ANTHROPIC_API_KEY in .env."}), 502
    except anthropic.RateLimitError:
        return jsonify({"error": "Rate limited by Claude. Wait a moment and try again."}), 429
    except anthropic.APIStatusError as exc:
        msg = getattr(exc, "message", "") or ""
        if "credit balance" in msg.lower():
            return jsonify({
                "error": "Your Anthropic account is out of API credits. Add some at "
                         "console.anthropic.com → Plans & Billing. (A Claude.ai "
                         "subscription doesn't cover API usage.)"
            }), 402
        logger.error("Claude API error %s: %s", exc.status_code, msg)
        return jsonify({"error": f"Claude returned an error ({exc.status_code})."}), 502
    except anthropic.APIConnectionError:
        return jsonify({"error": "Could not reach Claude. Check the server's connection."}), 502

    if response.stop_reason == "refusal":
        return jsonify({"error": "Claude declined to analyse these photos."}), 422

    text = "\n\n".join(b.text for b in response.content if b.type == "text").strip()
    if not text:
        return jsonify({"error": "Claude returned an empty response. Try again."}), 502

    newest = entries[-1]["id"]
    store.set_analysis(newest, text)
    return jsonify({"analysis": text, "entry_id": newest, "photos": len(entries)})


def _media_type(path):
    ext = os.path.splitext(path)[1].lower()
    return {".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")


@app.errorhandler(RequestEntityTooLarge)
def too_large(_):
    return jsonify({"error": "That photo is too big. Try a smaller one."}), 413
