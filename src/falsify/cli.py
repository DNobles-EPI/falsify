"""falsify — AI coding agent orchestrator CLI."""
from __future__ import annotations

import argparse
import importlib.metadata
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="falsify",
        description="Run the AI coding agent orchestration loop.",
    )
    parser.add_argument(
        "--port", type=int, default=8765, metavar="PORT",
        help="Observer dashboard port (default: 8765).",
    )
    parser.add_argument(
        "--no-observer", action="store_true",
        help="Disable the live HTTP dashboard.",
    )
    parser.add_argument(
        "--engine",
        default="dot",
        choices=("dot", "neato", "fdp", "sfdp", "circo", "twopi"),
        help="Graphviz layout engine for the dashboard (default: dot).",
    )
    parser.add_argument(
        "--max-steps", type=int, default=10_000, metavar="N",
        help="Safety limit on FSM poll iterations (default: 10 000).",
    )
    parser.add_argument(
        "--feat-branch", default="feat/agent", metavar="BRANCH",
        help="Feature branch name (default: feat/agent).",
    )
    args = parser.parse_args()

    try:
        version = importlib.metadata.version("falsify")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"

    # Imports deferred so --help is instant
    from falsify import AgentFSM, Context
    from falsify.observer import StateObserver

    print(f"\n  falsify {version}\n")

    ctx = Context(feat_branch=args.feat_branch)
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


if __name__ == "__main__":
    main()
