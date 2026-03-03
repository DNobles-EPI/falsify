#!/usr/bin/env python3
"""Generate the AgentFSM state machine diagram -> docs/statemachine.png"""
import argparse
from pathlib import Path
import subprocess
import sys

import graphviz

SUPPORTED_ENGINES = ("dot", "neato", "fdp", "sfdp", "circo", "twopi")

# Import graph structure from the FSM — single source of truth
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from falsify import AgentFSM  # noqa: E402

STATES = AgentFSM.states
TRANSITIONS = AgentFSM.edges

COLORS = {
    "PLAN":     "#cce5ff",
    "DONE":     "#d4edda",
}
DEFAULT_COLOR = "#f8f9fa"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--engine",
        action="append",
        default=[],
        help=(
            "Graphviz layout engine to use. Repeat this flag to render several "
            "engines, e.g. --engine dot --engine neato."
        ),
    )
    parser.add_argument(
        "--all-engines",
        action="store_true",
        help="Render diagrams for all supported engines.",
    )
    parser.add_argument(
        "--list-engines",
        action="store_true",
        help="Print supported engines and exit.",
    )
    return parser.parse_args()


def normalize_engines(raw_engines: list[str], all_engines: bool) -> list[str]:
    engines: list[str] = []
    for raw in raw_engines:
        engines.extend(part.strip() for part in raw.split(",") if part.strip())

    if all_engines:
        engines.extend(SUPPORTED_ENGINES)
    if not engines:
        engines = ["dot"]

    deduped: list[str] = []
    for engine in engines:
        if engine not in SUPPORTED_ENGINES:
            valid = ", ".join(SUPPORTED_ENGINES)
            raise ValueError(f"Unsupported engine '{engine}'. Supported: {valid}")
        if engine not in deduped:
            deduped.append(engine)
    return deduped


def render_diagram(out_dir: Path, engine: str, multiple: bool) -> Path:
    out_dir.mkdir(exist_ok=True)

    dot = graphviz.Digraph(
        "AgentFSM",
        engine=engine,
        graph_attr={
            "rankdir": "LR",
            "splines": "polyline",
            "fontname": "Helvetica",
            "bgcolor": "white",
        },
        node_attr={"fontname": "Helvetica", "fontsize": "11"},
        edge_attr={"fontname": "Helvetica", "fontsize": "9"},
    )

    for state in STATES:
        shape = "doublecircle" if state == "DONE" else "circle"
        color = COLORS.get(state, DEFAULT_COLOR)
        dot.node(state, shape=shape, style="filled", fillcolor=color)

    for src, dst, trigger in TRANSITIONS:
        dot.edge(src, dst, label=trigger)

    if multiple:
        out_path = out_dir / f"statemachine_{engine}"
    else:
        out_path = out_dir / "statemachine"
    dot.render(str(out_path), format="png", cleanup=True)
    return out_path.with_suffix(".png")


def main() -> None:
    args = parse_args()
    if args.list_engines:
        print("\n".join(SUPPORTED_ENGINES))
        return

    try:
        engines = normalize_engines(args.engine, args.all_engines)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    out_dir = Path(__file__).parent.parent / "docs"
    multiple = len(engines) > 1
    failed: list[str] = []
    for engine in engines:
        try:
            out_path = render_diagram(out_dir, engine, multiple=multiple)
            print(f"Wrote {out_path}")
        except subprocess.CalledProcessError as exc:
            failed.append(engine)
            print(f"Engine '{engine}' failed: {exc}", file=sys.stderr)

    if failed:
        failed_str = ", ".join(failed)
        raise SystemExit(f"Rendering failed for engine(s): {failed_str}")


if __name__ == "__main__":
    main()
