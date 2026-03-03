from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, List, Optional, Tuple

from transitions import Machine


# ── shell helpers ─────────────────────────────────────────────────────────────

def sh(cmd: List[str], cwd: Optional[str] = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)

def sh_json(cmd: List[str], cwd: Optional[str] = None) -> Any:
    p = sh(cmd, cwd=cwd, check=True)
    return json.loads(p.stdout)

def git(*args: str) -> str:
    return sh(["git", *args]).stdout

def gh(*args: str) -> str:
    return sh(["gh", *args]).stdout

def gh_json_cmd(*args: str) -> Any:
    return sh_json(["gh", *args])

def require_clean_tooling() -> None:
    # Helpful early failure
    sh(["git", "--version"])
    sh(["gh", "--version"])


# ── domain types ──────────────────────────────────────────────────────────────

CiStatus = Optional[Literal["running", "pass", "fail"]]


@dataclass
class Todo:
    kind: str
    payload: Any = None


@dataclass
class Test:
    file: str
    nodeid: str  # e.g. pytest nodeid


@dataclass
class Context:
    todos: List[Todo] = field(default_factory=list)
    git_dirty: bool = False
    impacted_tests: List[Test] = field(default_factory=list)
    failing: List[Tuple[Test, str]] = field(default_factory=list)  # (test, result/trace)
    pr_id: Optional[str] = None
    ci_status: CiStatus = None
    approved: bool = False
    feat_branch: str = "feat/agent"
    force_full_suite_next: bool = False


# ── state machine ─────────────────────────────────────────────────────────────

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

    # (source, dest, trigger) — single source of truth for graph structure.
    # Consumed by observer.py and scripts/gen_diagram.py.
    edges: List[Tuple[str, str, str]] = [
        ("PLAN",               "DO",                "todos_loaded"),
        ("DO",                 "LOCAL_VERIFY",      "todo_batch_done"),
        ("LOCAL_VERIFY",       "RUN_IMPACTED_TESTS","git_dirty"),
        ("LOCAL_VERIFY",       "PR_SYNC",           "git_clean"),
        ("RUN_IMPACTED_TESTS", "FIX_FAILING_TEST",  "any_fail"),
        ("RUN_IMPACTED_TESTS", "COMMIT",            "all_pass"),
        ("FIX_FAILING_TEST",   "RUN_IMPACTED_TESTS","patch_applied"),
        ("COMMIT",             "PLAN",              "committed"),
        ("PR_SYNC",            "WAIT_CI",           "pr_created_or_updated"),
        ("WAIT_CI",            "DONE",              "pr_approved"),
        ("WAIT_CI",            "TRIAGE_CI_FAIL",    "ci_failed"),
        ("WAIT_CI",            "WAIT_CI",           "checks_running"),
        ("WAIT_CI",            "PLAN",              "ci_passed_not_approved"),
        ("TRIAGE_CI_FAIL",     "PLAN",              "add_failure_to_todos"),
    ]

    def __init__(self, ctx: Optional[Context] = None):
        self.ctx = ctx or Context()

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
            queued=True,  # triggers in callbacks are queued, avoids re-entrancy weirdness
        )

    # ── guards ────────────────────────────────────────────────────────────────

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

    # ── state entry handlers ──────────────────────────────────────────────────

    def on_enter_PLAN(self):
        self.log("PLAN: load todos")
        self.load_todos()
        self.todos_loaded()

    def on_enter_DO(self):
        self.log(f"DO: {len(self.ctx.todos)} todos")
        self.do_todo_batch()
        self.todo_batch_done()

    def on_enter_LOCAL_VERIFY(self):
        self.refresh_git_status()
        self.log(f"LOCAL_VERIFY: git_dirty={self.ctx.git_dirty}")
        if self.is_git_dirty():
            self.git_dirty()
        else:
            self.git_clean()

    def on_enter_RUN_IMPACTED_TESTS(self):
        self.log("RUN_IMPACTED_TESTS: selecting impacted tests")
        self.select_impacted_tests()
        self.log(f"RUN_IMPACTED_TESTS: running {len(self.ctx.impacted_tests)} tests")
        self.run_tests()
        if self.any_failures():
            self.any_fail()
        else:
            self.all_pass()

    def on_enter_FIX_FAILING_TEST(self):
        self.log(f"FIX_FAILING_TEST: {len(self.ctx.failing)} failing")
        self.fix_one_failure()
        self.patch_applied()

    def on_enter_COMMIT(self):
        self.log("COMMIT: committing changes")
        self.git_commit()
        self.committed()

    def on_enter_PR_SYNC(self):
        self.log("PR_SYNC: sync PR to dev")
        self.pr_sync_to_dev()
        self.pr_created_or_updated()

    def on_enter_WAIT_CI(self):
        self.poll_ci()
        self.log(f"WAIT_CI: ci_status={self.ctx.ci_status} approved={self.ctx.approved}")

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
            self.ci_passed_not_approved()

    def on_enter_TRIAGE_CI_FAIL(self):
        self.log("TRIAGE_CI_FAIL: translating CI failure to todos")
        self.triage_ci_failure()
        self.add_failure_to_todos()

    def on_enter_DONE(self):
        self.log("DONE: PR approved")

    # ── actions ───────────────────────────────────────────────────────────────

    def load_todos(self) -> None:
        """Populate ctx.todos from unresolved PR review threads."""
        self.ctx.todos.clear()
        if not self.ctx.pr_id:
            return

        data = gh_json_cmd("pr", "view", self.ctx.pr_id, "--json", "reviewThreads")
        for thread in data.get("reviewThreads", []):
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

        self.log(f"  loaded {len(self.ctx.todos)} todos from PR #{self.ctx.pr_id}")

    def do_todo_batch(self) -> None:
        while self.ctx.todos:
            todo = self.ctx.todos.pop(0)
            self.log(f"  doing todo: {todo.kind}")
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
            self.log(f"  unhandled todo kind: {todo.kind!r}")

    def _invoke_agent(self, task: str) -> None:
        """
        Integration point: call your AI coding agent here.
        Example using Claude Code CLI:
            sh(["claude", "--print", task])
        """
        raise NotImplementedError("AI backend not connected — override _invoke_agent()")

    def refresh_git_status(self) -> None:
        out = git("status", "--porcelain").strip()
        self.ctx.git_dirty = (out != "")

    def _changed_files(self) -> List[str]:
        # Compare working tree against HEAD (includes staged + unstaged)
        out = git("diff", "--name-only", "HEAD").strip()
        files = [f for f in out.splitlines() if f.strip()]
        # Include staged but not committed
        out2 = git("diff", "--cached", "--name-only", "HEAD").strip()
        files += [f for f in out2.splitlines() if f.strip()]
        return sorted(set(files))

    def _candidate_test_paths_for_file(self, f: str) -> List[str]:
        """Map a changed source file to likely test files."""
        p = Path(f)
        candidates: List[Path] = []

        # If the change is already a test file, include it directly
        if "tests" in p.parts and p.suffix == ".py":
            candidates.append(p)

        # Simple basename mapping: src/foo/bar.py -> tests/test_bar.py
        stem = p.stem
        if p.suffix == ".py":
            candidates.append(Path("tests") / f"test_{stem}.py")
            candidates.append(Path("tests") / stem / f"test_{stem}.py")

        # Module-path mapping: src/foo/bar.py -> tests/foo/test_bar.py
        parts = list(p.parts)
        if parts and parts[0] in ("src",):
            rel = Path(*parts[1:])  # foo/bar.py
            candidates.append(Path("tests") / rel.parent / f"test_{rel.stem}.py")

        return [str(c) for c in candidates if c.exists()]

    def select_impacted_tests(self) -> None:
        if self.ctx.force_full_suite_next:
            self.log("  force_full_suite_next=True -> FULL_SUITE")
            self.ctx.force_full_suite_next = False
            self.ctx.impacted_tests = [Test(file="", nodeid="FULL_SUITE")]
            return

        changed = self._changed_files()
        self.log(f"  changed_files={len(changed)}")

        test_paths: List[str] = []
        for f in changed:
            test_paths.extend(self._candidate_test_paths_for_file(f))
        test_paths = sorted(set(test_paths))

        if not test_paths:
            self.ctx.impacted_tests = [Test(file="", nodeid="FULL_SUITE")]
            return

        self.ctx.impacted_tests = [Test(file=tp, nodeid=tp) for tp in test_paths]

    def run_tests(self) -> None:
        self.ctx.failing.clear()
        for test in self.ctx.impacted_tests:
            result = self.run_test(test)
            if result != "pass":
                self.ctx.failing.append((test, result))

    def run_test(self, test: Test) -> str:
        if test.nodeid == "FULL_SUITE":
            cmd = ["pytest", "-q"]
        else:
            cmd = ["pytest", "-q", test.nodeid]
        cmd += ["--maxfail=1"]
        p = subprocess.run(cmd, text=True, capture_output=True)
        if p.returncode == 0:
            return "pass"
        # Keep the blob short-ish; triage can fetch more later
        blob = (p.stdout + "\n" + p.stderr).strip()
        return blob[-4000:]

    def fix_one_failure(self) -> None:
        """Pass the first failing test's output to the agent for a fix."""
        if not self.ctx.failing:
            return
        test, result = self.ctx.failing[0]
        self.log(f"  fixing: {test.nodeid}")
        self._invoke_agent(
            f"Fix the failing test: {test.nodeid}\n\nTest output:\n{result}"
        )
        # Clear here; RUN_IMPACTED_TESTS will rerun and repopulate if still broken
        self.ctx.failing.clear()

    def git_commit(self) -> None:
        sh(["git", "add", "-A"])
        stat = sh(["git", "diff", "--cached", "--stat"]).stdout.strip()
        msg = f"agent: automated changes\n\n{stat}"
        sh(["git", "commit", "-m", msg])
        self.ctx.git_dirty = False

    def pr_sync_to_dev(self) -> None:
        require_clean_tooling()

        base = "dev"
        head = self.ctx.feat_branch

        sh(["git", "checkout", head])
        sh(["git", "push", "-u", "origin", head])

        # Find existing open PR for this head branch
        prs = gh_json_cmd(
            "pr", "list",
            "--head", head,
            "--state", "open",
            "--json", "number,url,headRefName,baseRefName",
        )

        if prs:
            self.ctx.pr_id = str(prs[0]["number"])
            return

        title = f"{head}: automated updates"
        body = "Automated changes by coding agent.\n\n- Local tests: impacted subset\n- CI: GitHub Actions\n"

        out = gh_json_cmd(
            "pr", "create",
            "--base", base,
            "--head", head,
            "--title", title,
            "--body", body,
            "--json", "number,url",
        )
        self.ctx.pr_id = str(out["number"])

    def poll_ci(self) -> None:
        """Update ctx.ci_status and ctx.approved."""
        if not self.ctx.pr_id:
            self.ctx.ci_status = None
            self.ctx.approved = False
            return

        pr_num = self.ctx.pr_id
        pr = gh_json_cmd("pr", "view", pr_num, "--json", "headRefOid,reviewDecision")
        sha = pr["headRefOid"]

        self.ctx.approved = (pr.get("reviewDecision") == "APPROVED")

        checks = gh_json_cmd(
            "api",
            f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs",
            "-q",
            "{check_runs: .check_runs | map({name: .name, status: .status, conclusion: .conclusion})}",
        )
        check_runs = checks.get("check_runs", [])

        if not check_runs:
            self.ctx.ci_status = "running"
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
        """Convert CI failure -> actionable Todo(s)."""
        if not self.ctx.pr_id:
            self.ctx.todos.append(Todo(kind="ci_failure", payload={"reason": "no_pr"}))
            return

        pr = gh_json_cmd("pr", "view", self.ctx.pr_id, "--json", "headRefOid")
        sha = pr["headRefOid"]

        checks = gh_json_cmd(
            "api",
            f"repos/{{owner}}/{{repo}}/commits/{sha}/check-runs",
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

        # If CI pytest job failed, force a full suite locally once
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

    # ── runner ────────────────────────────────────────────────────────────────

    def run(self, max_steps: int = 10_000) -> None:
        """
        Step the machine until DONE or max_steps.
        Because we use queued=True and triggers inside on_enter_*, the machine
        progresses naturally after entering PLAN.
        """
        steps = 0
        while self.state != "DONE" and steps < max_steps:
            steps += 1
            time.sleep(0.01)

        if self.state != "DONE":
            raise RuntimeError(f"FSM did not finish. state={self.state} steps={steps}")

    def log(self, msg: str) -> None:
        print(f"[{self.state}] {msg}")


if __name__ == "__main__":
    from observer import StateObserver

    fsm = AgentFSM()
    StateObserver(fsm).start()
    fsm.run()
