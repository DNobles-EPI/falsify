from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from transitions import Machine

from falsify.console import _BOLD, _DIM, _GREEN, _RED, _RST, _STATE_COL, _W
from falsify.shell import (
    build_codex_prompt,
    current_branch_name,
    gh,
    gh_graphql_json,
    gh_json_cmd,
    github_owner_repo,
    github_repo,
    git,
    parse_pr_number_from_url,
    pick_pr_base_branch,
    require_clean_tooling,
    sh,
    sh_stream,
)
from falsify.types import Context, Test, Todo


class AgentFSM:
    """
    Coarse FSM for an AI coding assistant orchestrator.

    Philosophy:
      - States are few and meaningful.
      - Details live in self.ctx.
      - Each state does some work, then emits exactly one transition event.
    """

    states = [
        "PLAN",
        "DO",
        "LOCAL_VERIFY",
        "RUN_IMPACTED_TESTS",
        "FIX_FAILING_TEST",
        "COMMIT",
        "PR_SYNC",
        "WAIT_CI",
        "TRIAGE_CI_FAIL",
        "DONE",
    ]

    edges: list[tuple[str, str, str]] = [
        ("PLAN", "DO", "todos_loaded"),
        ("DO", "LOCAL_VERIFY", "todo_batch_done"),
        ("LOCAL_VERIFY", "RUN_IMPACTED_TESTS", "git_dirty"),
        ("LOCAL_VERIFY", "PR_SYNC", "git_clean"),
        ("RUN_IMPACTED_TESTS", "FIX_FAILING_TEST", "any_fail"),
        ("RUN_IMPACTED_TESTS", "COMMIT", "all_pass"),
        ("FIX_FAILING_TEST", "RUN_IMPACTED_TESTS", "patch_applied"),
        ("COMMIT", "PLAN", "committed"),
        ("PR_SYNC", "WAIT_CI", "pr_created_or_updated"),
        ("WAIT_CI", "DONE", "pr_approved"),
        ("WAIT_CI", "TRIAGE_CI_FAIL", "ci_failed"),
        ("WAIT_CI", "WAIT_CI", "checks_running"),
        ("WAIT_CI", "WAIT_CI", "ci_passed_not_approved"),
        ("TRIAGE_CI_FAIL", "PLAN", "add_failure_to_todos"),
    ]

    def __init__(self, ctx: Optional[Context] = None) -> None:
        self.ctx = ctx or Context()
        self._start_time = time.monotonic()

        transitions = [
            dict(trigger=t, source=s, dest=d)
            for s, d, t in AgentFSM.edges
        ]

        self.machine = Machine(
            model=self,
            states=AgentFSM.states,
            transitions=transitions,
            initial="PLAN",
            auto_transitions=False,
            queued=True,
        )

    def has_todos(self) -> bool:
        return len(self.ctx.todos) > 0

    def is_git_dirty(self) -> bool:
        return self.ctx.git_dirty

    def any_failures(self) -> bool:
        return len(self.ctx.failing) > 0

    def pr_is_approved(self) -> bool:
        return bool(self.ctx.approved)

    def ci_running(self) -> bool:
        return self.ctx.ci_status == "running"

    def ci_failed_status(self) -> bool:
        return self.ctx.ci_status == "fail"

    def ci_passed_status(self) -> bool:
        return self.ctx.ci_status == "pass"

    def on_enter_PLAN(self):
        self.log("loading todos…")
        self.load_todos()
        self.todos_loaded()

    def on_enter_DO(self):
        n = len(self.ctx.todos)
        self.log(f"{n} todo{'s' if n != 1 else ''} queued")
        self.do_todo_batch()
        self.todo_batch_done()

    def on_enter_LOCAL_VERIFY(self):
        self.refresh_git_status()
        self.log("dirty" if self.ctx.git_dirty else "clean")
        if self.is_git_dirty():
            self.git_dirty()
        else:
            self.git_clean()

    def on_enter_RUN_IMPACTED_TESTS(self):
        self.select_impacted_tests()
        n = len(self.ctx.impacted_tests)
        self.log(f"{n} test{'s' if n != 1 else ''}")
        self.run_tests()
        if self.any_failures():
            self.any_fail()
        else:
            self.all_pass()

    def on_enter_FIX_FAILING_TEST(self):
        n = len(self.ctx.failing)
        self.log(f"{n} failing")
        self.fix_one_failure()
        self.patch_applied()

    def on_enter_COMMIT(self):
        self.log("staging and committing…")
        self.git_commit()
        self.committed()

    def on_enter_PR_SYNC(self):
        base = pick_pr_base_branch()
        self.log(f"push {self.ctx.feat_branch!r} → {base}")
        self.pr_sync_to_dev()
        self.log_detail(f"PR #{self.ctx.pr_id}")
        self.pr_created_or_updated()

    def on_enter_WAIT_CI(self):
        self.poll_ci()
        self.log(f"ci={self.ctx.ci_status or 'unknown'}  approved={self.ctx.approved}")

        if self.pr_is_approved():
            self.pr_approved()
            return

        if self.ci_failed_status():
            self.ci_failed()
            return

        if self.ci_running() or self.ctx.ci_status is None:
            time.sleep(10)
            self.checks_running()
            return

        if self.ci_passed_status() and not self.pr_is_approved():
            time.sleep(10)
            self.ci_passed_not_approved()

    def on_enter_TRIAGE_CI_FAIL(self):
        self.log("triaging CI failure…")
        self.triage_ci_failure()
        self.add_failure_to_todos()

    def on_enter_DONE(self):
        self.log("PR approved ✓")

    def load_todos(self) -> None:
        self.ctx.todos.clear()
        if not self.ctx.pr_id:
            return

        owner, repo_name = github_owner_repo()
        data = gh_graphql_json(
            """
            query($owner:String!, $repo:String!, $number:Int!) {
              repository(owner:$owner, name:$repo) {
                pullRequest(number:$number) {
                  reviewThreads(first:100) {
                    nodes {
                      isResolved
                      isOutdated
                      comments(first:100) {
                        nodes {
                          body
                          path
                          line
                        }
                      }
                    }
                  }
                }
              }
            }
            """,
            owner=owner,
            repo=repo_name,
            number=self.ctx.pr_id,
        )
        threads = (
            data.get("data", {})
            .get("repository", {})
            .get("pullRequest", {})
            .get("reviewThreads", {})
            .get("nodes", [])
        )
        for thread in threads:
            if thread.get("isResolved") or thread.get("isOutdated"):
                continue
            nodes = thread.get("comments", {}).get("nodes", [])
            if not nodes:
                continue
            first = nodes[0]
            self.ctx.todos.append(Todo(
                kind="review_comment",
                payload={
                    "body": first.get("body", ""),
                    "path": first.get("path"),
                    "line": first.get("line"),
                },
            ))

        self.log_detail(f"{len(self.ctx.todos)} todos from PR #{self.ctx.pr_id}")

    def do_todo_batch(self) -> None:
        while self.ctx.todos:
            todo = self.ctx.todos.pop(0)
            if todo.kind == "review_comment":
                path = todo.payload.get("path") or "?"
                line = todo.payload.get("line") or "?"
                desc = f"review_comment @ {path}:{line}"
            elif todo.kind == "ci_failure":
                detail = todo.payload.get("check") or todo.payload.get("reason", "?")
                desc = f"ci_failure: {detail}"
            else:
                desc = todo.kind
            self.log_detail(desc)
            self.do_todo(todo)

    def do_todo(self, todo: Todo) -> None:
        if todo.kind == "review_comment":
            body = todo.payload.get("body", "")
            path = todo.payload.get("path")
            line = todo.payload.get("line")
            location = f"{path}:{line}" if path and line else path or "(general)"
            self._invoke_agent(f"Address review comment at {location}:\n\n{body}")
        elif todo.kind == "ci_failure":
            check = todo.payload.get("check", "CI")
            reason = todo.payload.get("reason")
            url = todo.payload.get("details_url", "")
            if reason:
                self._invoke_agent(f"CI failure (reason={reason}). Investigate and fix.")
            else:
                self._invoke_agent(
                    f"CI check '{check}' failed. Details: {url}\n\nInvestigate and fix."
                )
        else:
            self.log_detail(f"unhandled todo kind: {todo.kind!r}")

    def _invoke_agent(self, task: str) -> None:
        prompt = build_codex_prompt(task)
        self.log_detail("launching codex…")
        sh_stream([
            "codex",
            "exec",
            "--full-auto",
            "-C",
            str(Path.cwd()),
            prompt,
        ])

    def refresh_git_status(self) -> None:
        out = git("status", "--porcelain").strip()
        self.ctx.git_dirty = (out != "")

    def _changed_files(self) -> list[str]:
        out = git("diff", "--name-only", "HEAD").strip()
        files = [f for f in out.splitlines() if f.strip()]
        out2 = git("diff", "--cached", "--name-only", "HEAD").strip()
        files += [f for f in out2.splitlines() if f.strip()]
        return sorted(set(files))

    def _candidate_test_paths_for_file(self, f: str) -> list[str]:
        p = Path(f)
        candidates: list[Path] = []

        if "tests" in p.parts and p.suffix == ".py":
            candidates.append(p)

        stem = p.stem
        if p.suffix == ".py":
            candidates.append(Path("tests") / f"test_{stem}.py")
            candidates.append(Path("tests") / stem / f"test_{stem}.py")

        parts = list(p.parts)
        if parts and parts[0] in ("src",):
            rel = Path(*parts[1:])
            candidates.append(Path("tests") / rel.parent / f"test_{rel.stem}.py")

        return [str(c) for c in candidates if c.exists()]

    def select_impacted_tests(self) -> None:
        if self.ctx.force_full_suite_next:
            self.log_detail("force full suite")
            self.ctx.force_full_suite_next = False
            self.ctx.impacted_tests = [Test(file="", nodeid="FULL_SUITE")]
            return

        changed = self._changed_files()
        self.log_detail(f"{len(changed)} changed file(s)")

        test_paths: list[str] = []
        for f in changed:
            test_paths.extend(self._candidate_test_paths_for_file(f))
        test_paths = sorted(set(test_paths))

        if not test_paths:
            self.log_detail("no mapped tests → full suite")
            self.ctx.impacted_tests = [Test(file="", nodeid="FULL_SUITE")]
            return

        self.ctx.impacted_tests = [Test(file=tp, nodeid=tp) for tp in test_paths]

    def run_tests(self) -> None:
        self.ctx.failing.clear()
        for test in self.ctx.impacted_tests:
            result = self.run_test(test)
            if result != "pass":
                self.ctx.failing.append((test, result))
                first_line = result.splitlines()[0] if result else "failed"
                self.log_detail(f"{_RED}✗{_RST} {test.nodeid}  {_DIM}{first_line}{_RST}")
            else:
                self.log_detail(f"{_GREEN}✓{_RST} {test.nodeid}")

    def run_test(self, test: Test) -> str:
        if test.nodeid == "FULL_SUITE":
            cmd = [sys.executable, "-m", "pytest", "-q"]
        else:
            cmd = [sys.executable, "-m", "pytest", "-q", test.nodeid]
        cmd += ["--maxfail=1"]
        p = subprocess.run(cmd, text=True, capture_output=True)
        if p.returncode == 0:
            return "pass"
        if test.nodeid == "FULL_SUITE" and (
            p.returncode == 5
            or "no tests ran" in (p.stdout + p.stderr).lower()
            or "collected 0 items" in (p.stdout + p.stderr).lower()
        ):
            return "pass"
        blob = (p.stdout + "\n" + p.stderr).strip()
        return blob[-4000:]

    def fix_one_failure(self) -> None:
        if not self.ctx.failing:
            return
        test, result = self.ctx.failing[0]
        self.log_detail(f"fix: {test.nodeid}")
        self._invoke_agent(
            f"Fix the failing test: {test.nodeid}\n\nTest output:\n{result}"
        )
        self.ctx.failing.clear()

    def git_commit(self) -> None:
        sh(["git", "add", "-A"])
        stat = sh(["git", "diff", "--cached", "--stat"]).stdout.strip()
        msg = f"agent: automated changes\n\n{stat}"
        sh(["git", "commit", "-m", msg])
        summary = stat.splitlines()[-1] if stat else "nothing staged"
        self.log_detail(summary)
        self.ctx.git_dirty = False

    def pr_sync_to_dev(self) -> None:
        require_clean_tooling()

        base = pick_pr_base_branch()
        head = self.ctx.feat_branch
        current = current_branch_name()
        repo = github_repo()

        if current == head:
            sh(["git", "push", "-u", "origin", head])
        else:
            sh(["git", "push", "origin", f"HEAD:refs/heads/{head}"])

        prs = gh_json_cmd(
            "pr", "list",
            "-R", repo,
            "--head", head,
            "--state", "open",
            "--json", "number,url,headRefName,baseRefName",
        )

        if prs:
            self.ctx.pr_id = str(prs[0]["number"])
            return

        title = f"{head}: automated updates"
        body = "Automated changes by coding agent.\n\n- Local tests: impacted subset\n- CI: GitHub Actions\n"

        url = gh(
            "pr", "create",
            "-R", repo,
            "--base", base,
            "--head", head,
            "--title", title,
            "--body", body,
        ).strip()

        prs = gh_json_cmd(
            "pr", "list",
            "-R", repo,
            "--head", head,
            "--state", "open",
            "--json", "number,url,headRefName,baseRefName",
        )
        if prs:
            self.ctx.pr_id = str(prs[0]["number"])
            return

        pr_id = parse_pr_number_from_url(url)
        if pr_id:
            self.ctx.pr_id = pr_id
            return

        raise RuntimeError(f"Created PR for {head!r}, but could not determine its number.")

    def poll_ci(self) -> None:
        if not self.ctx.pr_id:
            self.ctx.ci_status = None
            self.ctx.approved = False
            return

        pr_num = self.ctx.pr_id
        repo = github_repo()
        owner, name = github_owner_repo()
        pr = gh_json_cmd("pr", "view", pr_num, "-R", repo, "--json", "headRefOid,reviewDecision")
        sha = pr["headRefOid"]

        self.ctx.approved = (pr.get("reviewDecision") == "APPROVED")

        checks = gh_json_cmd(
            "api",
            f"repos/{owner}/{name}/commits/{sha}/check-runs",
            "-q",
            "{check_runs: .check_runs | map({name: .name, status: .status, conclusion: .conclusion})}",
        )
        check_runs = checks.get("check_runs", [])

        if not check_runs:
            self.ctx.ci_status = "pass"
            return

        any_in_progress = any(cr["status"] != "completed" for cr in check_runs)
        any_failed = any(
            cr["status"] == "completed" and cr["conclusion"] in (
                "failure", "cancelled", "timed_out", "action_required", "stale"
            )
            for cr in check_runs
        )
        all_passed = all(
            cr["status"] == "completed" and cr["conclusion"] in ("success", "neutral", "skipped")
            for cr in check_runs
        )

        if any_in_progress:
            self.ctx.ci_status = "running"
        elif any_failed:
            self.ctx.ci_status = "fail"
        elif all_passed:
            self.ctx.ci_status = "pass"
        else:
            self.ctx.ci_status = "running"

    def triage_ci_failure(self) -> None:
        if not self.ctx.pr_id:
            self.ctx.todos.append(Todo(kind="ci_failure", payload={"reason": "no_pr"}))
            return

        repo = github_repo()
        owner, name = github_owner_repo()
        pr = gh_json_cmd("pr", "view", self.ctx.pr_id, "-R", repo, "--json", "headRefOid")
        sha = pr["headRefOid"]

        checks = gh_json_cmd(
            "api",
            f"repos/{owner}/{name}/commits/{sha}/check-runs",
            "-q",
            "{check_runs: .check_runs | map({name: .name, status: .status, conclusion: .conclusion, details_url: .details_url})}",
        )
        check_runs = checks.get("check_runs", [])

        failing = [
            cr for cr in check_runs
            if cr["status"] == "completed" and cr["conclusion"] in (
                "failure", "cancelled", "timed_out", "action_required", "stale"
            )
        ]

        if not failing:
            self.ctx.todos.append(Todo(kind="ci_failure", payload={"reason": "unknown_failure"}))
            return

        cr = failing[0]
        check_name = (cr.get("name") or "").lower()

        if "pytest" in check_name or "unit" in check_name or "integration" in check_name:
            self.ctx.force_full_suite_next = True

        self.ctx.todos.append(
            Todo(
                kind="ci_failure",
                payload={
                    "check": cr["name"],
                    "conclusion": cr["conclusion"],
                    "details_url": cr.get("details_url"),
                },
            )
        )
        self.log_detail(f"→ todo: ci_failure ({cr['name']})")

    def run(self, max_steps: int = 10_000) -> None:
        import threading

        error: list[BaseException] = []

        def _target() -> None:
            try:
                self.on_enter_PLAN()
            except Exception as exc:  # noqa: BLE001
                error.append(exc)

        thread = threading.Thread(target=_target, daemon=True, name="fsm")
        thread.start()

        for _ in range(max_steps):
            if self.state == "DONE":
                return
            if error:
                raise error[0]
            time.sleep(0.1)

        raise RuntimeError(
            f"FSM did not reach DONE after {max_steps} checks. state={self.state}"
        )

    def log(self, msg: str) -> None:
        elapsed = time.monotonic() - self._start_time
        state = self.state
        col = _STATE_COL.get(state, "")
        t = f"{_DIM}{elapsed:6.1f}s{_RST}"
        s = f"{col}{_BOLD}{state:<{_W}}{_RST}"
        print(f"  {t}  {s}  {msg}", flush=True)

    def log_detail(self, msg: str) -> None:
        elapsed = time.monotonic() - self._start_time
        t = f"{_DIM}{elapsed:6.1f}s{_RST}"
        pad = " " * _W
        print(f"  {t}  {_DIM}{pad}  ↳ {_RST}{msg}", flush=True)
