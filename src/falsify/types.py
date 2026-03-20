from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


CiStatus = Optional[Literal["running", "pass", "fail"]]


@dataclass
class Todo:
    kind: str
    payload: Any = None


@dataclass
class Test:
    file: str
    nodeid: str


@dataclass
class Context:
    todos: list[Todo] = field(default_factory=list)
    git_dirty: bool = False
    impacted_tests: list[Test] = field(default_factory=list)
    failing: list[tuple[Test, str]] = field(default_factory=list)
    pr_id: Optional[str] = None
    ci_status: CiStatus = None
    approved: bool = False
    pr_merged: bool = False
    pr_closed: bool = False
    feat_branch: str = "feat/agent"
    force_full_suite_next: bool = False
