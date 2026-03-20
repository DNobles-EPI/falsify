from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any, Optional

from falsify.types import AgentBackend

def sh(
    cmd: list[str],
    cwd: Optional[str] = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or f"exit status {exc.returncode}"
        rendered = subprocess.list2cmdline(exc.cmd)
        raise RuntimeError(f"{rendered}: {detail}") from exc


def sh_stream(cmd: list[str], cwd: Optional[str] = None) -> None:
    try:
        subprocess.run(cmd, cwd=cwd, check=True, text=True)
    except subprocess.CalledProcessError as exc:
        rendered = subprocess.list2cmdline(exc.cmd)
        raise RuntimeError(f"{rendered}: exit status {exc.returncode}") from exc


def sh_json(cmd: list[str], cwd: Optional[str] = None) -> Any:
    p = sh(cmd, cwd=cwd, check=True)
    return json.loads(p.stdout)


def git(*args: str) -> str:
    return sh(["git", *args]).stdout


def gh(*args: str) -> str:
    return sh(["gh", *args]).stdout


def gh_json_cmd(*args: str) -> Any:
    return sh_json(["gh", *args])


def gh_graphql_json(query: str, **variables: str) -> Any:
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        cmd.extend(["-F", f"{key}={value}"])
    return sh_json(cmd)


def require_clean_tooling() -> None:
    sh(["git", "--version"])
    sh(["gh", "--version"])


def git_branch_exists(ref: str) -> bool:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref],
        text=True,
        capture_output=True,
    ).returncode == 0


def pick_pr_base_branch() -> str:
    for candidate in ("dev", "develop", "main", "master"):
        if git_branch_exists(candidate) or git_branch_exists(f"origin/{candidate}"):
            return candidate
    raise RuntimeError(
        "Could not determine a PR base branch. Tried: dev, develop, main, master."
    )


def current_branch_name() -> Optional[str]:
    branch = git("branch", "--show-current").strip()
    return branch or None


def parse_pr_number_from_url(url: str) -> Optional[str]:
    match = re.search(r"/pull/(\d+)(?:/|$)", url.strip())
    return match.group(1) if match else None


def build_agent_prompt(task: str) -> str:
    return (
        "You are operating inside the current git repository as an automated coding agent.\n"
        "Read the codebase, make the smallest correct changes to complete the task, and edit files directly.\n"
        "After changes, briefly summarize what you changed.\n\n"
        f"Task:\n{task}\n"
    )


def build_agent_command(
    backend: AgentBackend,
    prompt: str,
    cwd: Optional[str] = None,
) -> list[str]:
    workdir = cwd or os.getcwd()
    cmd = ["codex", "exec"]
    if backend == "codex-oss":
        cmd.extend(["--oss", "--local-provider", "ollama"])
    cmd.extend(["--full-auto", "-C", workdir, prompt])
    return cmd


def github_repo() -> str:
    url = git("remote", "get-url", "origin").strip()
    patterns = (
        r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return f"{match.group('owner')}/{match.group('repo')}"
    raise RuntimeError(f"Could not parse GitHub repo from origin remote: {url}")


def github_owner_repo() -> tuple[str, str]:
    owner, name = github_repo().split("/", 1)
    return owner, name
