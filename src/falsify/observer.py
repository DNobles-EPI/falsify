"""HTTP live state observer for AgentFSM."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List, Optional, Tuple

import graphviz

from falsify.shell import local_backend_compute

# ── graph styling ─────────────────────────────────────────────────────────────

_NODE_COLORS: Dict[str, str] = {
    "PLAN": "#cce5ff",
    "DONE": "#d4edda",
}
_NODE_DEFAULT  = "#f8f9fa"
_ACTIVE_FILL   = "#ff9800"
_ACTIVE_STROKE = "#bf360c"


def _build_svg(
    states: List[str],
    edges: List[Tuple[str, str, str]],
    active: str,
    engine: str = "dot",
) -> str:
    """Render the FSM as an SVG with *active* node highlighted."""
    dot = graphviz.Digraph(
        "AgentFSM",
        engine=engine,
        graph_attr={
            "rankdir": "LR",
            "splines": "polyline",
            "fontname": "Helvetica",
            "bgcolor": "white",
            "pad": "0.4",
        },
        node_attr={"fontname": "Helvetica", "fontsize": "11"},
        edge_attr={"fontname": "Helvetica", "fontsize": "9"},
    )
    for state in states:
        shape = "doublecircle" if state == "DONE" else "circle"
        if state == active:
            fill, stroke, pw = _ACTIVE_FILL, _ACTIVE_STROKE, "3"
        else:
            fill = _NODE_COLORS.get(state, _NODE_DEFAULT)
            stroke, pw = "black", "1"
        dot.node(state, shape=shape, style="filled",
                 fillcolor=fill, color=stroke, penwidth=pw)
    for src, dst, trigger in edges:
        dot.edge(src, dst, label=trigger)

    raw = dot.pipe(format="svg").decode("utf-8")
    # Strip XML/DOCTYPE preamble — inline SVG must start with <svg
    idx = raw.find("<svg")
    return raw[idx:] if idx >= 0 else raw


# ── dashboard HTML ─────────────────────────────────────────────────────────────

_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>falsify \u00b7 agent dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; }
  body { margin: 0; font-family: system-ui, -apple-system, sans-serif;
         background: #0d1117; color: #c9d1d9; }
  header { display: flex; align-items: center; justify-content: space-between;
           padding: 12px 24px; background: #161b22;
           border-bottom: 1px solid #30363d; }
  h1 { margin: 0; font-size: 1rem; color: #58a6ff; letter-spacing: .03em; }
  #status { font-size: .75rem; color: #8b949e; }

  .layout { display: grid; grid-template-columns: 1fr 300px;
            height: calc(100vh - 49px); }
  #graph-panel { padding: 24px; overflow: auto;
                 display: flex; align-items: center; justify-content: center; }
  #graph svg { max-width: 100%; height: auto; }

  aside { border-left: 1px solid #30363d; padding: 16px; overflow-y: auto;
          background: #161b22; display: flex; flex-direction: column; gap: 12px; }

  .card { background: #21262d; border: 1px solid #30363d;
          border-radius: 8px; padding: 14px; }
  .lbl { font-size: .7rem; text-transform: uppercase; letter-spacing: .08em;
         color: #8b949e; margin-bottom: 6px; }
  .val { font-size: 1.6rem; font-weight: 600; font-variant-numeric: tabular-nums; }
  #cur-state { color: #ff9800; }

  table { width: 100%; border-collapse: collapse; font-size: .8rem; }
  th { text-align: left; color: #8b949e; font-weight: 400;
       padding-bottom: 8px; border-bottom: 1px solid #30363d; }
  tr + tr td { padding-top: 5px; }
  .s-cell { white-space: nowrap; padding-right: 8px; }
  .row-active .s-cell { color: #ff9800; font-weight: 600; }

  .bar-bg { background: #0d1117; border-radius: 3px; height: 6px;
            width: 90px; display: inline-block; vertical-align: middle;
            overflow: hidden; }
  .bar { background: #30363d; border-radius: 3px; height: 6px;
         min-width: 2px; transition: width .4s ease; }
  .bar.hi { background: #ff9800; }
  .cnt { color: #8b949e; min-width: 26px; text-align: right;
         font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
<header>
  <h1>falsify &middot; agent dashboard</h1>
  <span id="status">connecting\u2026</span>
</header>
<div class="layout">
  <div id="graph-panel"><div id="graph">Loading\u2026</div></div>
  <aside>
    <div class="card">
      <div class="lbl">Agent backend</div>
      <div class="val" id="agent-backend">\u2014</div>
    </div>
    <div class="card" id="compute-card" style="display:none">
      <div class="lbl">Local compute</div>
      <div class="val" id="local-compute">\u2014</div>
    </div>
    <div class="card">
      <div class="lbl">Current state</div>
      <div class="val" id="cur-state">\u2014</div>
    </div>
    <div class="card">
      <div class="lbl">Time in state</div>
      <div class="val" id="elapsed">\u2014</div>
    </div>
    <div class="card">
      <div class="lbl">Visit counts</div>
      <table>
        <thead>
          <tr><th>State</th><th></th><th style="text-align:right">n</th></tr>
        </thead>
        <tbody id="counts-body"></tbody>
      </table>
    </div>
  </aside>
</div>
<script>
let lastState = null;

async function poll() {
  try {
    const r = await fetch('/state');
    const d = await r.json();
    document.getElementById('agent-backend').textContent = d.agent_backend;
    const computeCard = document.getElementById('compute-card');
    if (d.local_compute) {
      computeCard.style.display = '';
      document.getElementById('local-compute').textContent = d.local_compute;
    } else {
      computeCard.style.display = 'none';
    }
    document.getElementById('cur-state').textContent = d.state;
    document.getElementById('elapsed').textContent = d.elapsed_seconds + 's';
    document.getElementById('status').textContent =
      'live \u00b7 ' + new Date().toLocaleTimeString();
    updateCounts(d.state, d.visit_counts);
    if (d.state !== lastState) { lastState = d.state; await reloadGraph(); }
  } catch {
    document.getElementById('status').textContent = 'disconnected';
  }
}

async function reloadGraph() {
  try {
    const r = await fetch('/graph.svg?' + Date.now());
    document.getElementById('graph').innerHTML = await r.text();
  } catch {}
}

function updateCounts(active, counts) {
  const max = Math.max(1, ...Object.values(counts));
  const tbody = document.getElementById('counts-body');
  for (const [state, n] of Object.entries(counts)) {
    let row = document.getElementById('r-' + state);
    if (!row) {
      row = document.createElement('tr');
      row.id = 'r-' + state;
      row.innerHTML =
        `<td class="s-cell">${state}</td>` +
        `<td><div class="bar-bg"><div class="bar" id="b-${state}"></div></div></td>` +
        `<td class="cnt" id="c-${state}">0</td>`;
      tbody.appendChild(row);
    }
    row.className = state === active ? 'row-active' : '';
    const b = document.getElementById('b-' + state);
    b.style.width = (n / max * 100).toFixed(1) + '%';
    b.className = 'bar' + (state === active ? ' hi' : '');
    document.getElementById('c-' + state).textContent = n;
  }
}

reloadGraph();
poll();
setInterval(poll, 1000);
</script>
</body>
</html>"""


# ── observer ──────────────────────────────────────────────────────────────────

class StateObserver:
    """
    Monitors an AgentFSM and serves a live HTML dashboard over HTTP.

    Attaches with zero changes to the FSM: polls fsm.state every 50 ms in a
    daemon thread, re-renders the highlighted SVG on each state transition, and
    serves the dashboard + JSON + SVG via a second daemon thread.

    Usage:
        fsm = AgentFSM()
        StateObserver(fsm).start()
        fsm.run()
    """

    def __init__(
        self,
        fsm,
        *,
        host: str = "localhost",
        port: int = 8765,
        engine: str = "dot",
    ) -> None:
        self.fsm = fsm
        self.host = host
        self.port = port
        self.engine = engine

        self._lock = threading.Lock()
        self._state: str = fsm.state
        self._entered_at: float = time.monotonic()
        # One visit-count entry per state; start at zero for all
        self._visits: Dict[str, int] = {s: 0 for s in fsm.states}
        self._stop = threading.Event()
        # Cache one SVG per distinct active state (at most len(states) renders)
        self._svg_cache: Dict[str, str] = {}
        self._local_compute: Optional[str] = None
        self._local_compute_checked_at: float = 0.0

    # ── internals ─────────────────────────────────────────────────────────────

    def _svg_for(self, state: str) -> str:
        if state not in self._svg_cache:
            self._svg_cache[state] = _build_svg(
                self.fsm.states, self.fsm.edges, state, self.engine
            )
        return self._svg_cache[state]

    def _monitor(self) -> None:
        prev: Optional[str] = None
        while not self._stop.is_set():
            cur = self.fsm.state
            if cur != prev:
                now = time.monotonic()
                with self._lock:
                    self._state = cur
                    self._entered_at = now
                    self._visits[cur] += 1
                prev = cur
            time.sleep(0.05)

    # ── public API ────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """Return a JSON-serialisable snapshot of current observer state."""
        with self._lock:
            backend = getattr(self.fsm.ctx, "agent_backend", "codex")
            local_compute = None
            if backend == "codex-oss":
                now = time.monotonic()
                if now - self._local_compute_checked_at >= 1.0:
                    self._local_compute = local_backend_compute()
                    self._local_compute_checked_at = now
                local_compute = self._local_compute
            return {
                "agent_backend": backend,
                "local_compute": local_compute,
                "state": self._state,
                "elapsed_seconds": round(time.monotonic() - self._entered_at, 1),
                "visit_counts": dict(self._visits),
            }

    def current_svg(self) -> str:
        with self._lock:
            state = self._state
        return self._svg_for(state)

    def start(self) -> StateObserver:
        """Start monitor + HTTP server as daemon threads; returns self."""
        threading.Thread(
            target=self._monitor, daemon=True, name="fsm-monitor"
        ).start()

        obs = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path = self.path.split("?")[0]
                if path == "/":
                    self._send(200, "text/html; charset=utf-8", _HTML.encode())
                elif path == "/state":
                    self._send(200, "application/json",
                               json.dumps(obs.snapshot()).encode())
                elif path == "/graph.svg":
                    self._send(200, "image/svg+xml",
                               obs.current_svg().encode())
                else:
                    self.send_error(404)

            def _send(self, code: int, ct: str, body: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_) -> None:
                pass  # silence request logs

        server = HTTPServer((self.host, self.port), _Handler)
        threading.Thread(
            target=server.serve_forever, daemon=True, name="fsm-http"
        ).start()
        print(f"[observer] http://{self.host}:{self.port}")
        return self

    def stop(self) -> None:
        self._stop.set()
