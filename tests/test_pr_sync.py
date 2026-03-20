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


def test_pr_sync_reuses_latest_merged_pr_when_no_commits_between_branches(monkeypatch) -> None:
    fsm = AgentFSM(Context(feat_branch="feat/agent"))
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr("falsify.fsm.require_clean_tooling", lambda: None)
    monkeypatch.setattr("falsify.fsm.pick_pr_base_branch", lambda: "develop")
    monkeypatch.setattr("falsify.fsm.current_branch_name", lambda: "feat/agent")
    monkeypatch.setattr("falsify.fsm.github_repo", lambda: "owner/repo")
    monkeypatch.setattr(fsm, "log_detail", lambda msg: None)

    def fake_sh(cmd: list[str], cwd=None, check: bool = True):
        calls.append(tuple(cmd))

        class Result:
            stdout = ""

        return Result()

    def fake_gh(*args: str):
        raise RuntimeError("gh pr create: No commits between develop and feat/agent")

    def fake_gh_json_cmd(*args: str):
        if args[:2] == ("pr", "list") and "--state" in args:
            state = args[args.index("--state") + 1]
            if state == "open":
                return []
            if state == "merged":
                return [{"number": 4, "baseRefName": "develop"}]
        raise AssertionError(f"unexpected gh_json_cmd call: {args}")

    monkeypatch.setattr("falsify.fsm.sh", fake_sh)
    monkeypatch.setattr("falsify.fsm.gh", fake_gh)
    monkeypatch.setattr("falsify.fsm.gh_json_cmd", fake_gh_json_cmd)

    fsm.pr_sync_to_dev()

    assert ("git", "push", "-u", "origin", "feat/agent") in calls
    assert fsm.ctx.pr_id == "4"


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


def test_load_todos_uses_graphql_review_threads(monkeypatch) -> None:
    fsm = AgentFSM(Context())
    fsm.ctx.pr_id = "3"

    monkeypatch.setattr("falsify.fsm.github_owner_repo", lambda: ("owner", "repo"))

    def fake_gh_graphql_json(query: str, **variables: str):
        assert "reviewThreads" in query
        assert variables == {"owner": "owner", "repo": "repo", "number": "3"}
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {
                                    "isResolved": False,
                                    "isOutdated": False,
                                    "comments": {
                                        "nodes": [
                                            {
                                                "body": "please fix this",
                                                "path": "src/falsify/fsm.py",
                                                "line": 123,
                                            }
                                        ]
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        }

    monkeypatch.setattr("falsify.fsm.gh_graphql_json", fake_gh_graphql_json)

    fsm.load_todos()

    assert len(fsm.ctx.todos) == 1
    assert fsm.ctx.todos[0].kind == "review_comment"
    assert fsm.ctx.todos[0].payload["path"] == "src/falsify/fsm.py"


def test_wait_ci_keeps_polling_when_ci_passed_but_not_approved(monkeypatch) -> None:
    fsm = AgentFSM(Context())
    events: list[str] = []

    monkeypatch.setattr(
        fsm,
        "poll_ci",
        lambda: (
            setattr(fsm.ctx, "ci_status", "pass"),
            setattr(fsm.ctx, "approved", False),
        ),
    )
    monkeypatch.setattr("falsify.fsm.time.sleep", lambda _: None)
    monkeypatch.setattr(fsm, "ci_passed_not_approved", lambda: events.append("wait"))

    fsm.on_enter_WAIT_CI()

    assert events == ["wait"]


def test_poll_ci_marks_merged_pr_as_terminal(monkeypatch) -> None:
    fsm = AgentFSM(Context())
    fsm.ctx.pr_id = "4"

    monkeypatch.setattr("falsify.fsm.github_repo", lambda: "owner/repo")
    monkeypatch.setattr("falsify.fsm.github_owner_repo", lambda: ("owner", "repo"))

    def fake_gh_json_cmd(*args: str):
        if args[:2] == ("pr", "view"):
            return {
                "headRefOid": "abc123",
                "reviewDecision": "",
                "state": "MERGED",
                "mergedAt": "2026-03-20T00:00:00Z",
            }
        if args[:1] == ("api",):
            return {"check_runs": []}
        raise AssertionError(f"unexpected gh_json_cmd call: {args}")

    monkeypatch.setattr("falsify.fsm.gh_json_cmd", fake_gh_json_cmd)

    fsm.poll_ci()

    assert fsm.ctx.pr_merged is True
    assert fsm.ctx.pr_closed is False


def test_wait_ci_stops_when_pr_is_merged(monkeypatch) -> None:
    fsm = AgentFSM(Context())
    events: list[str] = []

    monkeypatch.setattr(
        fsm,
        "poll_ci",
        lambda: (
            setattr(fsm.ctx, "ci_status", "pass"),
            setattr(fsm.ctx, "approved", False),
            setattr(fsm.ctx, "pr_merged", True),
            setattr(fsm.ctx, "pr_closed", False),
        ),
    )
    monkeypatch.setattr(fsm, "pr_approved", lambda: events.append("done"))

    fsm.on_enter_WAIT_CI()

    assert events == ["done"]


def test_wait_ci_raises_when_pr_closed_without_merge(monkeypatch) -> None:
    fsm = AgentFSM(Context())

    monkeypatch.setattr(
        fsm,
        "poll_ci",
        lambda: (
            setattr(fsm.ctx, "ci_status", "pass"),
            setattr(fsm.ctx, "approved", False),
            setattr(fsm.ctx, "pr_merged", False),
            setattr(fsm.ctx, "pr_closed", True),
            setattr(fsm.ctx, "pr_id", "5"),
        ),
    )

    try:
        fsm.on_enter_WAIT_CI()
    except RuntimeError as exc:
        assert "closed without merge" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for closed PR")
