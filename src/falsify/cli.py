"""falsify — AI coding agent orchestrator CLI."""
from __future__ import annotations

import argparse
import importlib.metadata
import os
import sys

# Subcommand names — used for backwards-compat defaulting below.
_SUBCOMMANDS = {"run", "doctor"}


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--agent-backend",
        default="codex",
        choices=("codex", "codex-oss"),
        help="Agent backend to use for fix tasks (default: codex).",
    )
    p.add_argument(
        "--port", type=int, default=8765, metavar="PORT",
        help="Observer dashboard port (default: 8765).",
    )
    p.add_argument(
        "--no-observer", action="store_true",
        help="Disable the live HTTP dashboard.",
    )
    p.add_argument(
        "--engine",
        default="dot",
        choices=("dot", "neato", "fdp", "sfdp", "circo", "twopi"),
        help="Graphviz layout engine for the dashboard (default: dot).",
    )
    p.add_argument(
        "--max-steps", type=int, default=10_000, metavar="N",
        help="Safety limit on FSM poll iterations (default: 10 000).",
    )
    p.add_argument(
        "--feat-branch", default="falsify_agent", metavar="BRANCH",
        help="Feature branch name (default: falsify_agent).",
    )


def _cmd_run(args: argparse.Namespace) -> None:
    try:
        version = importlib.metadata.version("falsify")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"

    # Deferred imports so --help is instant.
    from falsify import AgentFSM, Context
    from falsify.observer import StateObserver

    print(f"\n  {args.prog_name} {version}\n")

    ctx = Context(feat_branch=args.feat_branch, agent_backend=args.agent_backend)
    fsm = AgentFSM(ctx=ctx)

    if not args.no_observer:
        StateObserver(fsm, port=args.port, engine=args.engine).start()
        print()

    try:
        fsm.run(max_steps=args.max_steps)
    except KeyboardInterrupt:
        print("\n  interrupted", file=sys.stderr)
        sys.exit(130)
    except RuntimeError as exc:
        print(f"\n  error: {exc}", file=sys.stderr)
        sys.exit(1)


def _cmd_doctor(_args: argparse.Namespace) -> None:
    from falsify.doctor import run_doctor
    ok = run_doctor(_args.agent_backend)
    sys.exit(0 if ok else 1)


def main() -> None:
    prog_name = os.path.basename(sys.argv[0]) or "falsify"

    # Backwards-compat: bare `falsify [--flags]` (no subcommand) → `falsify run [--flags]`.
    if len(sys.argv) < 2 or sys.argv[1] not in _SUBCOMMANDS:
        sys.argv.insert(1, "run")

    parser = argparse.ArgumentParser(
        prog=prog_name,
        description="AI coding agent orchestration loop.",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # ── run ───────────────────────────────────────────────────────────────────
    run_p = subparsers.add_parser(
        "run",
        help="Run the agent FSM (default when no subcommand is given).",
    )
    _add_run_args(run_p)
    run_p.set_defaults(func=_cmd_run)

    # ── doctor ────────────────────────────────────────────────────────────────
    doctor_p = subparsers.add_parser(
        "doctor",
        help="Check system prerequisites.",
    )
    doctor_p.add_argument(
        "--agent-backend",
        default="codex",
        choices=("codex", "codex-oss"),
        help="Agent backend to validate (default: codex).",
    )
    doctor_p.set_defaults(func=_cmd_doctor)

    args = parser.parse_args()
    args.prog_name = prog_name
    args.func(args)


if __name__ == "__main__":
    main()
