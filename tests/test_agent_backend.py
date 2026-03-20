from __future__ import annotations

import sys

from falsify import AgentFSM, Context
from falsify.doctor import Check, run_doctor
from falsify.shell import build_agent_command


def test_build_agent_command_for_codex() -> None:
    cmd = build_agent_command("codex", "fix it", "/tmp/repo")

    assert cmd == [
        "codex",
        "exec",
        "--full-auto",
        "-C",
        "/tmp/repo",
        "fix it",
    ]


def test_build_agent_command_for_codex_oss() -> None:
    cmd = build_agent_command("codex-oss", "fix it", "/tmp/repo")

    assert cmd == [
        "codex",
        "exec",
        "--oss",
        "--local-provider",
        "ollama",
        "--full-auto",
        "-C",
        "/tmp/repo",
        "fix it",
    ]


def test_invoke_agent_uses_selected_backend(monkeypatch) -> None:
    fsm = AgentFSM(Context(agent_backend="codex-oss"))
    calls: list[list[str]] = []

    monkeypatch.setattr("falsify.fsm.sh_stream", lambda cmd, cwd=None: calls.append(cmd))
    monkeypatch.setattr(fsm, "log_detail", lambda msg: None)

    fsm._invoke_agent("Fix the test")

    assert calls == [[
        "codex",
        "exec",
        "--oss",
        "--local-provider",
        "ollama",
        "--full-auto",
        "-C",
        str(__import__("pathlib").Path.cwd()),
        "You are operating inside the current git repository as an automated coding agent.\n"
        "Read the codebase, make the smallest correct changes to complete the task, and edit files directly.\n"
        "After changes, briefly summarize what you changed.\n\n"
        "Task:\nFix the test\n",
    ]]


def test_run_doctor_codex_checks_login(monkeypatch) -> None:
    called = {"login": False}

    ok_check = lambda label: Check(label=label, ok=True, detail="ok")

    monkeypatch.setattr("falsify.doctor.check_python", lambda: ok_check("python"))
    monkeypatch.setattr("falsify.doctor.check_curl", lambda: ok_check("curl"))
    monkeypatch.setattr("falsify.doctor.check_nodejs", lambda: ok_check("node"))
    monkeypatch.setattr("falsify.doctor.check_npm", lambda: ok_check("npm"))
    monkeypatch.setattr("falsify.doctor.check_git", lambda: ok_check("git"))
    monkeypatch.setattr("falsify.doctor.check_gh_installed", lambda: ok_check("gh"))
    monkeypatch.setattr("falsify.doctor.check_gh_auth", lambda: ok_check("gh auth"))
    monkeypatch.setattr("falsify.doctor.check_graphviz", lambda: ok_check("graphviz"))
    monkeypatch.setattr("falsify.doctor.check_pytest", lambda: ok_check("pytest"))
    monkeypatch.setattr("falsify.doctor.check_codex", lambda: ok_check("codex"))

    def fake_check_codex_login() -> Check:
        called["login"] = True
        return ok_check("codex login")

    monkeypatch.setattr("falsify.doctor.check_codex_login", fake_check_codex_login)

    assert run_doctor("codex") is True
    assert called["login"] is True


def test_run_doctor_codex_oss_skips_login(monkeypatch) -> None:
    called = {"login": False}

    ok_check = lambda label: Check(label=label, ok=True, detail="ok")

    monkeypatch.setattr("falsify.doctor.check_python", lambda: ok_check("python"))
    monkeypatch.setattr("falsify.doctor.check_curl", lambda: ok_check("curl"))
    monkeypatch.setattr("falsify.doctor.check_nodejs", lambda: ok_check("node"))
    monkeypatch.setattr("falsify.doctor.check_npm", lambda: ok_check("npm"))
    monkeypatch.setattr("falsify.doctor.check_git", lambda: ok_check("git"))
    monkeypatch.setattr("falsify.doctor.check_gh_installed", lambda: ok_check("gh"))
    monkeypatch.setattr("falsify.doctor.check_gh_auth", lambda: ok_check("gh auth"))
    monkeypatch.setattr("falsify.doctor.check_graphviz", lambda: ok_check("graphviz"))
    monkeypatch.setattr("falsify.doctor.check_pytest", lambda: ok_check("pytest"))
    monkeypatch.setattr("falsify.doctor.check_codex", lambda: ok_check("codex"))
    monkeypatch.setattr("falsify.doctor.check_ollama_reachable", lambda: ok_check("ollama"))
    monkeypatch.setattr("falsify.doctor.check_ollama_model", lambda: ok_check("model"))

    def fake_check_codex_login() -> Check:
        called["login"] = True
        return ok_check("codex login")

    monkeypatch.setattr("falsify.doctor.check_codex_login", fake_check_codex_login)

    assert run_doctor("codex-oss") is True
    assert called["login"] is False


def test_cli_run_defaults_to_codex_backend(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_cmd_run(args) -> None:
        captured["backend"] = args.agent_backend

    monkeypatch.setattr("falsify.cli._cmd_run", fake_cmd_run)
    monkeypatch.setattr(sys, "argv", ["falsify", "run"])

    from falsify import cli

    cli.main()

    assert captured["backend"] == "codex"


def test_cli_doctor_parses_codex_oss_backend(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_cmd_doctor(args) -> None:
        captured["backend"] = args.agent_backend

    monkeypatch.setattr("falsify.cli._cmd_doctor", fake_cmd_doctor)
    monkeypatch.setattr(sys, "argv", ["falsify", "doctor", "--agent-backend", "codex-oss"])

    from falsify import cli

    cli.main()

    assert captured["backend"] == "codex-oss"
