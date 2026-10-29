"""Typed contracts shared by deterministic and hybrid checkers."""

from dataclasses import asdict, dataclass, field
from abc import ABC, abstractmethod
from typing import Any, Literal

AssessmentState = Literal["clear", "flagged", "unknown", "not_applicable", "skipped"]


class BaseChecker(ABC):
    """Extension interface; handler plugins can implement this contract."""

    @abstractmethod
    def run(self, context: dict, spec: dict, settings: dict) -> "Assessment":
        raise NotImplementedError


@dataclass
class Assessment:
    check_id: str
    state: AssessmentState
    reason: str
    evidence: list[Any] = field(default_factory=list)
    execution_status: str = "completed"
    issue_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Issue:
    issue_id: str
    problem_id: str
    claim: str
    evidence: list[Any]
    certainty: Literal["confirmed", "suspected"] = "confirmed"
    severity: str = "blocker"
    revision_hash: str = ""
    depends_on_issue_ids: list[str] = field(default_factory=list)
    root_cause_group: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
