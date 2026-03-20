"""falsify doctor — pre-flight checks and interactive setup."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
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


def _probe_url(url: str) -> tuple[bool, str]:
    code, out = _run_cmd([
        "curl",
        "-fsS",
        "--max-time",
        "3",
        url,
    ])
    return code == 0, out or "unreachable"


def _candidate_ollama_hosts() -> list[str]:
    hosts = ["127.0.0.1", "localhost", "host.docker.internal"]
    resolv_conf = Path("/etc/resolv.conf")
    if resolv_conf.exists():
        for line in resolv_conf.read_text().splitlines():
            line = line.strip()
            if line.startswith("nameserver "):
                host = line.split()[1]
                if host not in hosts:
                    hosts.append(host)
    return hosts


def detect_ollama_base_url() -> Optional[str]:
    env_url = os.environ.get("OLLAMA_HOST", "").strip()
    candidates = []
    if env_url:
        if env_url.startswith("http://") or env_url.startswith("https://"):
            candidates.append(env_url.rstrip("/"))
        else:
            candidates.append(f"http://{env_url.rstrip('/')}")
    candidates.extend(f"http://{host}:11434" for host in _candidate_ollama_hosts())

    seen: set[str] = set()
    for base_url in candidates:
        if base_url in seen:
            continue
        seen.add(base_url)
        ok, _ = _probe_url(f"{base_url}/api/tags")
        if ok:
            return base_url
    return None


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
        hint="poetry add pytest" if not ok else "",
    )

def check_codex() -> Check:
    code, out = _run_cmd(["codex", "--version"])
    ok = code == 0
    return Check(
        label="codex",
        ok=ok,
        detail=out.splitlines()[0] if ok else "not found",
        hint="Install codex CLI" if not ok else "",
    )
    # # install codex cli via npm
    # npm i -g @openai/codex

def check_codex_login() -> Check:
    code, out = _run_cmd(["codex", "login", "status"])
    ok = code == 0
    return Check(
        label="codex login",
        ok=ok,
        detail=out.splitlines()[0] if ok else "not found",
        hint="need codex login" if not ok else "",
    )


def check_ollama_reachable() -> Check:
    base_url = detect_ollama_base_url()
    ok = base_url is not None
    return Check(
        label="ollama",
        ok=ok,
        detail=base_url or "not reachable",
        hint=(
            "Start Ollama in WSL or on the Windows host, or set OLLAMA_HOST."
            if not ok else ""
        ),
    )


def check_ollama_model(model: str = "gpt-oss:20b") -> Check:
    if shutil.which("ollama") is None:
        return Check(
            label=f"ollama model {model}",
            ok=False,
            detail="ollama CLI not found",
            hint=f"Install Ollama CLI and pull the model: ollama pull {model}",
        )

    code, out = _run_cmd(["ollama", "list"])
    ok = code == 0 and model in out
    return Check(
        label=f"ollama model {model}",
        ok=ok,
        detail=model if ok else "not installed",
        hint=f"Run: ollama pull {model}" if not ok else "",
    )

def check_nodejs() -> Check:
    code, out = _run_cmd(["node", "-v"])
    ok = code == 0
    return Check(
        label="Node.js",
        ok=ok,
        detail=out.splitlines()[0] if ok else "not found",
        hint="check nodejs installation" if not ok else "",
        # # install Node.js
        # curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
        # sudo apt install nodejs -y
    )

def check_npm() -> Check:
    code, out = _run_cmd(["npm", "-v"])
    ok = code == 0
    return Check(
        label="npm",
        ok=ok,
        detail=out.splitlines()[0] if ok else "not found",
        hint="check npm installation" if not ok else "",
        # # install Node.js
        # curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
        # sudo apt install nodejs -y
    )

def check_curl() -> Check:
    code, out = _run_cmd(["curl", "-V"])
    ok = code == 0
    return Check(
        label="curl",
        ok=ok,
        detail=out.splitlines()[0] if ok else "not found",
        hint="check curl installation" if not ok else "",
        # # install curl
        # sudo apt install curl -y
    )


# ── display ───────────────────────────────────────────────────────────────────

def _print_check(c: Check) -> None:
    icon = _TICK if c.ok else _CROSS
    detail = f"  {_DIM}{c.detail}{_RST}" if c.detail else ""
    print(f"  {icon}  {_BOLD}{c.label}{_RST}{detail}")
    if not c.ok and c.hint:
        print(f"       {_YELLOW}-> {c.hint}{_RST}")


# ── main entry point ──────────────────────────────────────────────────────────

def run_doctor(agent_backend: str = "codex") -> bool:
    """
    Run all pre-flight checks.

    Returns True if every check passes, False otherwise.
    """
    print(f"\n  {_BOLD}falsify doctor{_RST}\n")

    checks: list[Check] = [
        check_python(),
        check_curl(),
        check_nodejs(),
        check_npm(),
        check_git(),
        check_gh_installed(),
        check_gh_auth(),
        check_graphviz(),
        check_pytest(),
    ]

    if agent_backend == "codex":
        checks.extend([
            check_codex(),
            check_codex_login(),
        ])
    elif agent_backend == "codex-oss":
        checks.extend([
            check_codex(),
            check_ollama_reachable(),
            check_ollama_model(),
        ])
    else:
        raise RuntimeError(f"Unsupported agent backend: {agent_backend}")

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

if __name__ == "__main__":
    run_doctor()
