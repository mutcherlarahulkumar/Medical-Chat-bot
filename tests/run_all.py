"""Run every test module in this folder:  python tests/run_all.py"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
modules = sorted(p.name for p in HERE.glob("test_*.py"))

failed = []
for module in modules:
    print(f"\n{'#' * 60}\n#  {module}\n{'#' * 60}")
    if subprocess.run([sys.executable, module], cwd=HERE).returncode:
        failed.append(module)

print(f"\n{'=' * 60}")
if failed:
    print(f"  FAILED: {', '.join(failed)}")
else:
    print(f"  All {len(modules)} test modules passed.")
print("=" * 60)
sys.exit(1 if failed else 0)
