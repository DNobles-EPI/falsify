"""falsify doctor — pre-flight checks and interactive setup."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional


# ── colours ───────────────────────────────────────────────────────────────────

_TTY    = sys.stdout.isatty()
_RST    = "\x1b[0m"  if _TTY else ""
_BOLD   = "\x1b[1m"  if _TTY else ""
_DIM    = "\x1b[2m"  if _TTY else ""
_GREEN  = "\x1b[32m" if _TTY else ""
_YELLOW = "\x1b[33m" if _TTY else ""
_RED    = "\x1b[31m" if _TTY else ""

_TICK  = f"{_GREEN}✔{_RST}"
_CROSS = f"{_RED}✘{_RST}"
_WARN  = f"{_YELLOW}⚠{_RST}"

KEYRING_SERVICE = "falsify"


# ── keyring helpers ───────────────────────────────────────────────────────────

def _keyring_available() -> bool:
    try:
        import keyring  # noqa: F401
        return True
    except ImportError:
        return False


def get_api_key(name: str) -> Optional[str]:
    """
    Retrieve a stored API key.

    Priority: environment variable → OS keyring.

    The environment variable name is derived as ``<NAME>_API_KEY``
    (upper-cased, hyphens replaced with underscores), e.g.
    ``ANTHROPIC_API_KEY`` for name ``"anthropic"``.
    """
    env_var = f"{name.upper().replace('-', '_')}_API_KEY"
    if val := os.environ.get(env_var):
        return val

    if _keyring_available():
        try:
            import keyring
            return keyring.get_password(KEYRING_SERVICE, name)
        except Exception:
            pass

    return None


def set_api_key(name: str, value: str) -> bool:
    """
    Store *value* in the OS keyring under *name*.

    Returns True on success, False if keyring is unavailable or storage failed.
    """
    if not _keyring_available():
        return False
    try:
        import keyring
        keyring.set_password(KEYRING_SERVICE, name, value)
        return True
    except Exception:
        return False


def delete_api_key(name: str) -> None:
    """Remove *name* from the keyring (best-effort, silently ignores errors)."""
    if not _keyring_available():
        return
    try:
        import keyring
        keyring.delete_password(KEYRING_SERVICE, name)
    except Exception:
        pass


# ── check primitives ──────────────────────────────────────────────────────────

@dataclass
class Check:
    label: str
    ok: bool
    detail: str = ""
    hint: str = ""
    fixable: bool = False


def _run_cmd(args: list[str]) -> tuple[int, str]:
    """Run *args*, return (returncode, combined stdout+stderr)."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=10)
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return 1, "not found"
    except subprocess.TimeoutExpired:
        return 1, "timed out"


# ── individual checks ─────────────────────────────────────────────────────────

def check_python() -> Check:
    v = sys.version_info
    ok = v >= (3, 12)
    return Check(
        label="Python >= 3.12",
        ok=ok,
        detail=f"{v.major}.{v.minor}.{v.micro}",
        hint="Upgrade Python to 3.12+: https://python.org/downloads/" if not ok else "",
    )


def check_git() -> Check:
    code, out = _run_cmd(["git", "--version"])
    ok = code == 0
    return Check(
        label="git",
        ok=ok,
        detail=out.splitlines()[0] if ok else "not found",
        hint="Install git: https://git-scm.com/" if not ok else "",
    )


def check_gh_installed() -> Check:
    if shutil.which("gh") is None:
        return Check(
            label="gh (GitHub CLI)",
            ok=False,
            detail="not found",
            hint="Install gh: https://cli.github.com/",
        )
    code, out = _run_cmd(["gh", "--version"])
    ok = code == 0
    return Check(
        label="gh (GitHub CLI)",
        ok=ok,
        detail=out.splitlines()[0] if ok else out,
        hint="Install gh: https://cli.github.com/" if not ok else "",
    )


def check_gh_auth() -> Check:
    if shutil.which("gh") is None:
        return Check(label="gh auth", ok=False, detail="gh not installed")
    code, out = _run_cmd(["gh", "auth", "status"])
    ok = code == 0
    return Check(
        label="gh auth",
        ok=ok,
        detail="authenticated" if ok else "not authenticated",
        hint="Run: gh auth login" if not ok else "",
    )


def check_graphviz() -> Check:
    code, out = _run_cmd(["dot", "-V"])
    ok = code == 0
    return Check(
        label="graphviz (dot)",
        ok=ok,
        detail=out.splitlines()[0] if ok else "not found",
        hint="Install graphviz: https://graphviz.org/download/ (apt: graphviz, brew: graphviz)" if not ok else "",
    )


def check_pytest() -> Check:
    code, out = _run_cmd([sys.executable, "-m", "pytest", "--version"])
    ok = code == 0
    return Check(
        label="pytest",
        ok=ok,
        detail=out.splitlines()[0] if ok else "not found",
        hint="pip install pytest" if not ok else "",
    )


def check_keyring() -> Check:
    available = _keyring_available()
    detail = "available" if available else "not installed"
    if available:
        try:
            import keyring
            backend = type(keyring.get_keyring()).__name__
            detail = f"available ({backend})"
        except Exception:
            pass
    return Check(
        label="keyring (secure storage)",
        ok=available,
        detail=detail,
        hint=(
            "pip install keyring  "
            "(API keys fall back to environment variables without it)"
        ) if not available else "",
    )


# ── display ───────────────────────────────────────────────────────────────────

def _print_check(c: Check) -> None:
    icon = _TICK if c.ok else _CROSS
    detail = f"  {_DIM}{c.detail}{_RST}" if c.detail else ""
    print(f"  {icon}  {_BOLD}{c.label}{_RST}{detail}")
    if not c.ok and c.hint:
        print(f"       {_YELLOW}-> {c.hint}{_RST}")


# ── main entry point ──────────────────────────────────────────────────────────

def run_doctor() -> bool:
    """
    Run all pre-flight checks.

    Returns True if every check passes, False otherwise.
    """
    print(f"\n  {_BOLD}falsify doctor{_RST}\n")

    checks: list[Check] = [
        check_python(),
        check_git(),
        check_gh_installed(),
        check_gh_auth(),
        check_graphviz(),
        check_pytest(),
        check_keyring(),
    ]

    for c in checks:
        _print_check(c)

    # ── summary ───────────────────────────────────────────────────────────────
    all_ok = all(c.ok for c in checks)
    failing = [c for c in checks if not c.ok]

    print()
    if all_ok:
        print(f"  {_GREEN}{_BOLD}All checks passed.{_RST}")
    else:
        noun = "check" if len(failing) == 1 else "checks"
        print(f"  {_RED}{_BOLD}{len(failing)} {noun} failed.{_RST}")
        if not sys.stdin.isatty():
            for c in failing:
                if c.hint:
                    print(f"  {_DIM}* {c.label}: {c.hint}{_RST}")
    print()

    return all_ok
