from falsify import AgentFSM, Context
from falsify.observer import StateObserver


def test_snapshot_includes_agent_backend() -> None:
    fsm = AgentFSM(Context(agent_backend="codex-oss"))
    observer = StateObserver(fsm)

    snapshot = observer.snapshot()

    assert snapshot["agent_backend"] == "codex-oss"
    assert snapshot["state"] == "PLAN"
