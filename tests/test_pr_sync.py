from falsify import AgentFSM, Context
from falsify.shell import github_repo


def test_pr_sync_uses_head_push_when_checkout_is_detached(monkeypatch) -> None:
    fsm = AgentFSM(Context(feat_branch="feat/agent"))
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr("falsify.fsm.require_clean_tooling", lambda: None)
    monkeypatch.setattr("falsify.fsm.pick_pr_base_branch", lambda: "develop")
    monkeypatch.setattr("falsify.fsm.current_branch_name", lambda: None)
    monkeypatch.setattr("falsify.fsm.github_repo", lambda: "owner/repo")

    def fake_sh(cmd: list[str], cwd=None, check: bool = True):
        calls.append(tuple(cmd))

        class Result:
            stdout = ""

        return Result()

    def fake_gh_json_cmd(*args: str):
        if args[:2] == ("pr", "list"):
            return [{"number": 1}]
        raise AssertionError(f"unexpected gh_json_cmd call: {args}")

    monkeypatch.setattr("falsify.fsm.sh", fake_sh)
    monkeypatch.setattr("falsify.fsm.gh_json_cmd", fake_gh_json_cmd)

    fsm.pr_sync_to_dev()

    assert ("git", "push", "origin", "HEAD:refs/heads/feat/agent") in calls
    assert fsm.ctx.pr_id == "1"


def test_github_repo_accepts_dotted_repository_names(monkeypatch) -> None:
    monkeypatch.setattr(
        "falsify.shell.git",
        lambda *args: "git@github.com:example/my.repo.git\n",
    )

    assert github_repo() == "example/my.repo"


def test_poll_ci_marks_no_checks_as_pass(monkeypatch) -> None:
    fsm = AgentFSM(Context())
    fsm.ctx.pr_id = "2"

    monkeypatch.setattr("falsify.fsm.github_repo", lambda: "owner/repo")
    monkeypatch.setattr("falsify.fsm.github_owner_repo", lambda: ("owner", "repo"))

    def fake_gh_json_cmd(*args: str):
        if args[:2] == ("pr", "view"):
            return {"headRefOid": "abc123", "reviewDecision": ""}
        if args[:1] == ("api",):
            return {"check_runs": []}
        raise AssertionError(f"unexpected gh_json_cmd call: {args}")

    monkeypatch.setattr("falsify.fsm.gh_json_cmd", fake_gh_json_cmd)

    fsm.poll_ci()

    assert fsm.ctx.ci_status == "pass"
    assert fsm.ctx.approved is False
