# 🌸 Skin Tracker

A single-page, mobile-first skincare journal. Take a face photo each day, tick
off the products you used, and let Claude compare the last few photos to tell
you whether your texture, oiliness and breakouts are actually moving.

Runs on its own — it does **not** load MediBot's torch / faiss / transformers
stack.

## Run it

```bash
pip install flask python-dotenv anthropic     # or: pip install -r ../requirements.txt
cp ../.env.example ../.env                    # then fill in ANTHROPIC_API_KEY
python ../run_skin_tracker.py
```

Open <http://localhost:5001>. To use it on your phone, open
`http://<your-computer-ip>:5001` from the same Wi-Fi network.

Without an `ANTHROPIC_API_KEY` everything still works — photos, routine,
timeline — only the **Analyze** button is disabled, and the header says so.

## What's where

| File | Purpose |
|---|---|
| `app.py` | Flask routes + the Claude call (`/api/analyze`) |
| `templates/skin_tracker.html` | The whole UI — HTML, CSS and JS in one file |
| `../run_skin_tracker.py` | Entry point, port 5001 |

## How it stores things

Photos never reach the server's disk. Every entry — the JPEG, the timestamp,
the product list, your note and Claude's last update — lives in the browser's
**IndexedDB**, on that device only. Photos are downscaled to 1200px and
re-encoded as JPEG (quality 0.82) before being stored, which keeps a year of
daily photos comfortably inside the browser's quota.

Images are only transmitted when you tap **Analyze**: the newest entry plus up
to three previous ones are base64-encoded, POSTed to `/api/analyze`, forwarded
to Claude, and dropped. Clearing your browser data deletes everything.

## The three tabs

**Today** — take or choose a photo, tick the products you applied, add an
optional note, save, and analyze. Tapping Analyze on an unsaved photo saves it
first.

**Routine** — your product list. Add anything (`Niacinamide 10%`, `Rose Water
Toner`), reorder with ↑ / ↓, remove with ✕. The order is the order you apply
them, it numbers the checkboxes on the Today tab, and it's what Claude is told.
Defaults: Face Wash, Serum, Moisturizer, Sunscreen. Removing a product does not
alter entries you already saved.

**Timeline** — every entry, newest first, with its thumbnail, product chips,
note and progress update.

## The Claude call

`POST /api/analyze` takes `{"entries": [{photo, label, products, note}, ...]}`
oldest-first and returns `{"analysis": "..."}`.

- Model: `claude-sonnet-4-6` (override with `SKIN_TRACKER_MODEL`)
- Adaptive thinking on, `max_tokens` 4000
- The system prompt pins the response to four headings — Texture, Oiliness,
  Breakouts, Suggestion — under 200 words, and requires Claude to flag lighting
  differences rather than pass them off as skin changes.
- Guardrails: no diagnosis, no comments on anything but skin, and an explicit
  "show this to a dermatologist" when something looks like it needs real
  medical attention.

Limits: 4 photos per request, 4 MB each, 25 MB per request.

## Not medical advice

This is a habit tracker. It cannot diagnose anything, and photo-based
impressions are heavily affected by lighting and camera angle. Anything
painful, bleeding, spreading or changing shape belongs with a dermatologist.
