"""
run_skin_tracker.py — Start the Skin Tracker
============================================
    python run_skin_tracker.py

Then open http://localhost:5001 (or http://<your-laptop-ip>:5001 on your phone,
which is where it's meant to be used).

Runs independently of MediBot — it only needs `flask` and `anthropic`.
"""

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from skin_tracker.app import app, MODEL

if __name__ == "__main__":
    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))
    print("=" * 60)
    print("  🌸 Skin Tracker")
    print("=" * 60)
    print(f"  URL    : http://localhost:5001")
    print(f"  Model  : {MODEL}")
    print(f"  Claude : {'ready' if has_key else 'no ANTHROPIC_API_KEY — analysis disabled'}")
    print("  Phone  : open http://<this-machine-ip>:5001 on the same Wi-Fi")
    print("  Stop   : Ctrl + C")
    print("=" * 60)
    app.run(debug=True, host="0.0.0.0", port=5001)
