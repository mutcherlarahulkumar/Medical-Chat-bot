"""
Test bootstrap.

These tests exercise the request/response logic, which is pure Python. The
heavy runtime dependencies (torch, faiss, langchain) are only stubbed when they
are not installed, so the same tests run in a full environment unchanged.
"""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def install_optional_stubs():
    """Stub dotenv / langchain_core only if they are genuinely missing."""
    try:
        import dotenv  # noqa: F401
    except ImportError:
        mod = types.ModuleType("dotenv")
        mod.load_dotenv = lambda *a, **k: False
        sys.modules["dotenv"] = mod

    try:
        from langchain_core.messages import HumanMessage  # noqa: F401
    except ImportError:
        core = types.ModuleType("langchain_core")
        messages = types.ModuleType("langchain_core.messages")

        class HumanMessage:
            def __init__(self, content=""):
                self.content = content

        messages.HumanMessage = HumanMessage
        core.messages = messages
        sys.modules.setdefault("langchain_core", core)
        sys.modules["langchain_core.messages"] = messages


class Result:
    """Tiny assertion recorder so the suite runs with or without pytest."""

    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, name, condition, detail=""):
        if condition:
            self.passed += 1
            print(f"  PASS  {name}")
        else:
            self.failed += 1
            print(f"  FAIL  {name} {detail}")

    def finish(self):
        print(f"\n{'=' * 54}\n  {self.passed} passed, {self.failed} failed\n{'=' * 54}")
        return 1 if self.failed else 0
