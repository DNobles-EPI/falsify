from falsify import AgentFSM, Context
from falsify.observer import StateObserver


def test_snapshot_includes_agent_backend() -> None:
    fsm = AgentFSM(Context(agent_backend="codex"))
    observer = StateObserver(fsm)

    snapshot = observer.snapshot()

    assert snapshot["agent_backend"] == "codex"
    assert snapshot["local_compute"] is None
    assert snapshot["state"] == "PLAN"


def test_snapshot_includes_local_compute_for_codex_oss(monkeypatch) -> None:
    fsm = AgentFSM(Context(agent_backend="codex-oss"))
    observer = StateObserver(fsm)

    monkeypatch.setattr("falsify.observer.local_backend_compute", lambda: "47%/53% CPU/GPU")

    snapshot = observer.snapshot()

    assert snapshot["agent_backend"] == "codex-oss"
    assert snapshot["local_compute"] == "47%/53% CPU/GPU"
