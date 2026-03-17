from __future__ import annotations

import sys


_TTY = sys.stdout.isatty()
_RST = "\x1b[0m" if _TTY else ""
_BOLD = "\x1b[1m" if _TTY else ""
_DIM = "\x1b[2m" if _TTY else ""
_GREEN = "\x1b[32m" if _TTY else ""
_RED = "\x1b[31m" if _TTY else ""

_STATE_COL: dict[str, str] = ({
    "PLAN": "\x1b[34m",
    "DO": "\x1b[36m",
    "LOCAL_VERIFY": "\x1b[36m",
    "RUN_IMPACTED_TESTS": "\x1b[36m",
    "FIX_FAILING_TEST": "\x1b[33m",
    "COMMIT": "\x1b[32m",
    "PR_SYNC": "\x1b[32m",
    "WAIT_CI": "\x1b[35m",
    "TRIAGE_CI_FAIL": "\x1b[31m",
    "DONE": "\x1b[32m",
} if _TTY else {})

_W = 22
