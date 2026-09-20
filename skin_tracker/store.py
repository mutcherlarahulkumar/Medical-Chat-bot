"""
skin_tracker/store.py — server-side storage
===========================================
Entries live in SQLite; photos are plain JPEGs on disk beside it. Both sit in
`skin_tracker/data/`, which is gitignored.

Why not the browser? IndexedDB is per-device: clear your browsing data and the
history is gone, and your phone and laptop each keep a separate, unsyncable
copy. Storing on the server means every device that can reach it sees the same
timeline.
"""

import base64
import json
import os
import re
import sqlite3
import threading

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
PHOTO_DIR = os.path.join(DATA_DIR, "photos")
DB_PATH = os.path.join(DATA_DIR, "tracker.db")

MAX_IMAGE_BYTES = 6 * 1024 * 1024
ALLOWED_MEDIA = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
DEFAULT_PRODUCTS = ["Face Wash", "Serum", "Moisturizer", "Sunscreen"]

_DATA_URL = re.compile(r"^data:(image/[a-zA-Z+]+);base64,(.+)$", re.DOTALL)
_init_lock = threading.Lock()
_ready = False


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    """Create the data directory and tables. Safe to call repeatedly."""
    global _ready
    with _init_lock:
        if _ready:
            return
        os.makedirs(PHOTO_DIR, exist_ok=True)
        with _connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entries (
                    id       INTEGER PRIMARY KEY,
                    ts       INTEGER NOT NULL,
                    photo    TEXT    NOT NULL,
                    products TEXT    NOT NULL DEFAULT '[]',
                    note     TEXT    NOT NULL DEFAULT '',
                    analysis TEXT    NOT NULL DEFAULT ''
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS entries_ts ON entries(ts DESC)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )""")
        _ready = True


def decode_photo(data_url, label="Photo"):
    """data URL -> (media_type, raw bytes). Raises ValueError with a human message."""
    match = _DATA_URL.match((data_url or "").strip())
    if not match:
        raise ValueError(f"{label} is not a readable image.")

    media_type, payload = match.group(1), match.group(2)
    if media_type not in ALLOWED_MEDIA:
        raise ValueError(f"{label} uses an unsupported format ({media_type}).")
    try:
        raw = base64.b64decode(payload, validate=True)
    except Exception:
        raise ValueError(f"{label} could not be decoded.")
    if not raw:
        raise ValueError(f"{label} is empty.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"{label} is too large — keep it under 6 MB.")
    return media_type, raw


def _row_to_entry(row):
    return {
        "id": row["id"],
        "ts": row["ts"],
        "products": json.loads(row["products"]),
        "note": row["note"],
        "analysis": row["analysis"],
        "photo_url": f"/api/photo/{row['id']}",
    }


def add_entry(data_url, products, note, ts):
    """Write the photo to disk and the metadata to SQLite. Returns the entry."""
    init()
    media_type, raw = decode_photo(data_url, "Your photo")
    ext = ALLOWED_MEDIA[media_type]
    name = f"{ts}{ext}"

    path = os.path.join(PHOTO_DIR, name)
    with open(path, "wb") as fh:
        fh.write(raw)

    products = [str(p)[:64] for p in (products or []) if isinstance(p, str)]
    note = str(note or "")[:500]
    try:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO entries (id, ts, photo, products, note) VALUES (?,?,?,?,?)",
                (ts, ts, name, json.dumps(products), note),
            )
    except Exception:
        os.remove(path)          # don't leave an orphan photo behind
        raise
    return get_entry(ts)


def get_entry(entry_id):
    init()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
    return _row_to_entry(row) if row else None


def list_entries(limit=400):
    """Newest first."""
    init()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM entries ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_entry(r) for r in rows]


def photo_path(entry_id):
    init()
    with _connect() as conn:
        row = conn.execute("SELECT photo FROM entries WHERE id = ?", (entry_id,)).fetchone()
    if not row:
        return None
    # The filename comes from our own INSERT, but never trust it as a path.
    safe = os.path.basename(row["photo"])
    path = os.path.join(PHOTO_DIR, safe)
    return path if os.path.exists(path) else None


def set_analysis(entry_id, text):
    init()
    with _connect() as conn:
        conn.execute("UPDATE entries SET analysis = ? WHERE id = ?", (text, entry_id))


def delete_entry(entry_id):
    init()
    path = photo_path(entry_id)
    with _connect() as conn:
        changed = conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,)).rowcount
    if changed and path:
        try:
            os.remove(path)
        except OSError:
            pass
    return bool(changed)


def get_routine():
    init()
    with _connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'products'").fetchone()
    if not row:
        return DEFAULT_PRODUCTS[:]
    try:
        saved = json.loads(row["value"])
    except ValueError:
        return DEFAULT_PRODUCTS[:]
    return saved if isinstance(saved, list) and saved else DEFAULT_PRODUCTS[:]


def set_routine(products):
    init()
    clean, seen = [], set()
    for p in products or []:
        if not isinstance(p, str):
            continue
        name = p.strip()[:64]
        if name and name.lower() not in seen:
            seen.add(name.lower())
            clean.append(name)
    if len(clean) > 40:
        raise ValueError("That's more than 40 products — trim the list a bit.")
    with _connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('products', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(clean),),
        )
    return clean


def stats():
    init()
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) n, MIN(ts) first FROM entries").fetchone()
    size = sum(
        os.path.getsize(os.path.join(PHOTO_DIR, f))
        for f in os.listdir(PHOTO_DIR)
        if os.path.isfile(os.path.join(PHOTO_DIR, f))
    ) if os.path.isdir(PHOTO_DIR) else 0
    return {"entries": row["n"], "first_entry": row["first"], "photo_bytes": size}
