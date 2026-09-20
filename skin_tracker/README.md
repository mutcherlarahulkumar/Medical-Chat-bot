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

Photos and entries are written to `skin_tracker/data/`, which is gitignored.

## What's where

| File | Purpose |
|---|---|
| `app.py` | Routes, PWA plumbing, and the Claude call |
| `store.py` | SQLite + photo storage |
| `templates/skin_tracker.html` | The whole UI — HTML, CSS and JS in one file |
| `data/` | Your photos and database (gitignored) |
| `../run_skin_tracker.py` | Entry point, port 5001 |
| `../mobile/` | Capacitor config for building an APK |
| `../ANDROID.md` | Getting it onto your phone |

## How it stores things

Everything lives **on the server**, in `skin_tracker/data/` (gitignored):

- `tracker.db` — SQLite: timestamps, product logs, notes, Claude's updates
- `photos/<timestamp>.jpg` — the images themselves

That means your phone and your laptop see the same timeline, and clearing your
browser data doesn't lose anything. Photos are downscaled to 1200px JPEG in the
browser before upload (quality 0.82), so a year of daily photos is ~70 MB.

Photos are sent to Anthropic only when you tap **Analyze**, and only the latest
four. Back up by copying `skin_tracker/data/`.

## Cost

Analysis runs on the Claude API, which bills separately from any Claude.ai
subscription — a Pro or Max plan does **not** cover it. Add credits at
[console.anthropic.com](https://console.anthropic.com) → Plans & Billing.
Roughly 2¢ per analysis (4 photos + prompt on Sonnet 4.6), so $5 is about 250
progress checks. Everything except the Analyze button works with no credits at
all.

## On your phone

See [`../ANDROID.md`](../ANDROID.md). Short version: run the server, open
`http://<your-computer-ip>:5001` on your phone, tap **Install on my phone**.
It installs as a PWA with its own icon and fullscreen window.

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

`POST /api/analyze` takes only `{"labels": {entry_id: "Friday, 19 September, 8:30 AM"}}`
— the photos are already on the server, so the browser doesn't re-upload them.
It returns `{"analysis": "...", "entry_id": N}` and saves the update onto the
newest entry.

Other endpoints: `GET/POST /api/entries`, `DELETE /api/entries/<id>`,
`GET /api/photo/<id>`, `GET/PUT /api/routine`, `GET /health`.

- Model: `claude-sonnet-4-6` (override with `SKIN_TRACKER_MODEL`)
- Adaptive thinking on, `max_tokens` 4000
- The system prompt pins the response to four headings — Texture, Oiliness,
  Breakouts, Suggestion — under 200 words, and requires Claude to flag lighting
  differences rather than pass them off as skin changes.
- Guardrails: no diagnosis, no comments on anything but skin, and an explicit
  "show this to a dermatologist" when something looks like it needs real
  medical attention.

Limits: 4 photos per analysis, 6 MB per upload.

## Not medical advice

This is a habit tracker. It cannot diagnose anything, and photo-based
impressions are heavily affected by lighting and camera angle. Anything
painful, bleeding, spreading or changing shape belongs with a dermatologist.
