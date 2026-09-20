"""
build_index.py — MediBot v5
-----------------------------
Extended to handle trusted sources subfolder and provide build stats.
✅ Interface unchanged: python build_index.py
✅ Added --force flag to force full rebuild.
"""

import sys
import logging
import argparse
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="MediBot v5 — Build FAISS Knowledge Index")
    parser.add_argument("--force", action="store_true", help="Force rebuild even if index exists")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("MediBot v5 — Building Enhanced Medical Knowledge Index")
    logger.info("=" * 60)

    # Check data directories
    medical_dir = ROOT / "medical_data"
    trusted_dir = medical_dir / "trusted_sources"

    logger.info(f"Medical data folder : {medical_dir}")
    logger.info(f"Trusted sources     : {trusted_dir}")

    # Count available files
    txt_files = list(medical_dir.rglob("*.txt"))
    pdf_files = list(medical_dir.rglob("*.pdf"))
    trusted   = list(trusted_dir.glob("*.txt")) if trusted_dir.exists() else []

    logger.info(f"TXT files found     : {len(txt_files)}")
    logger.info(f"PDF files found     : {len(pdf_files)}")
    logger.info(f"Trusted source files: {len(trusted)}")

    if not txt_files and not pdf_files:
        logger.warning("No medical data files found! Add TXTs or PDFs to medical_data/")

    logger.info("-" * 60)

    from rag.rag_engine import build_vector_index
    build_vector_index(force_rebuild=args.force)

    # Report index stats
    faiss_dir = ROOT / "faiss_index"
    if faiss_dir.exists():
        index_size = sum(f.stat().st_size for f in faiss_dir.iterdir()) / 1024
        logger.info("-" * 60)
        logger.info(f"✅ Index built successfully in {faiss_dir}/")
        logger.info(f"   Index size: {index_size:.1f} KB")
    else:
        logger.error("❌ Index build failed — faiss_index/ not created")

    logger.info("=" * 60)
    logger.info("Next: python run.py  →  open http://localhost:5000")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
