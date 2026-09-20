"""
run.py — Start the Multimodal Medical Assistant
================================================
    python run.py

Then open:  http://localhost:5000
"""

import sys
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from flask_app.app import app

if __name__ == "__main__":
    print("=" * 60)
    print("  🏥 MediBot — Multimodal Medical Assistant")
    print("=" * 60)
    print("  URL    : http://localhost:5000")
    print("  Routes : /          — Chat UI")
    print("           /analyze   — Text query (original, preserved)")
    print("           /analyze-multimodal — Text + X-Ray")
    print("           /health    — Status check")
    print("  Stop   : Ctrl + C")
    print("=" * 60)
    app.run(debug=True, host="0.0.0.0", port=5000)
