from __future__ import annotations

import json
import subprocess
from typing import Any, Optional


def sh(
    cmd: list[str],
    cwd: Optional[str] = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)


def sh_json(cmd: list[str], cwd: Optional[str] = None) -> Any:
    p = sh(cmd, cwd=cwd, check=True)
    return json.loads(p.stdout)


def git(*args: str) -> str:
    return sh(["git", *args]).stdout


def gh(*args: str) -> str:
    return sh(["gh", *args]).stdout


def gh_json_cmd(*args: str) -> Any:
    return sh_json(["gh", *args])


def require_clean_tooling() -> None:
    sh(["git", "--version"])
    sh(["gh", "--version"])
