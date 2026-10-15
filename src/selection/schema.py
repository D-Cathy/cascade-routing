from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

class CallNotStartedError(ValueError):
    """Preflight/reservation failed: no backend attempt was dispatched."""


class ModelLevel(str, Enum):
    SHIP = "ship"
    SHORE = "shore"
    CLOUD = "cloud"
    @classmethod
    def order(cls):
        return {"ship": 0, "shore": 1, "cloud": 2}

class ActionType(str, Enum):
    ACCEPT = "ACCEPT"
    CALL = "CALL"
    FAIL = "FAIL"

class RequestStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    INDETERMINATE = "INDETERMINATE"

class ModelStatus(str, Enum):
    UNATTEMPTED = "UNATTEMPTED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    INVALID = "INVALID"

class ServiceFailureReason(str, Enum):
    LOW_QUALITY = "LOW_QUALITY"
    TIMEOUT = "TIMEOUT"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    NO_VALID_ANSWER = "NO_VALID_ANSWER"

@dataclass
class ModelCallRecord:
    model_name: str
    level: str
    status: ModelStatus
    latency: Optional[float]
    cost: Optional[float]
    answer: Optional[str] = None
    quality: Optional[float] = None  # evaluation only; never copied into controller state
    reason: Optional[str] = None
    attempted_once: bool = True
    model_version: str = "synthetic-v1"
    data_source: str = "synthetic"
    latency_source: str = "simulated"
    cost_source: str = "simulated"
    known_cost: float = 0.0  # lower bound when total cost is unknown
    metadata: dict = field(default_factory=dict)

@dataclass
class ObservableState:
    question: str
    evidence: str
    allowed_models: list[str]
    attempted_models: dict = field(default_factory=dict)
    successful_models: dict = field(default_factory=dict)
    failed_models: dict = field(default_factory=dict)
    invalid_models: dict = field(default_factory=dict)
    current_quality_estimate: Optional[float] = None
    remaining_time: Optional[float] = None
    remaining_budget: Optional[float] = None
    current_best_answer: Optional[str] = None
    current_best_quality: Optional[float] = None  # predicted, never a reference label
    quality_threshold: float = 0.8
    deadline: float = 0.0
    budget: float = 0.0
    environment: dict = field(default_factory=dict)
    def to_observable_dict(self):
        return asdict(self)

@dataclass
class ActionDecision:
    action_type: ActionType
    model_name: Optional[str] = None
    reason: Optional[str] = None

@dataclass
class TraceRecord:
    request_id: str
    question: str
    evidence: str
    source_group_id: str = "unspecified"
    status: RequestStatus = RequestStatus.RUNNING
    final_answer: Optional[str] = None
    final_model: Optional[str] = None
    final_quality: Optional[float] = None
    final_valid: Optional[bool] = None
    total_time: Optional[float] = 0.0
    total_cost: Optional[float] = 0.0
    known_time: float = 0.0
    known_cost: float = 0.0
    decision_time: float = 0.0
    measured_controller_time: float = 0.0
    cumulative_calls: int = 0
    model_calls: list = field(default_factory=list)
    failure_reasons: list = field(default_factory=list)
    unknown_checks: list = field(default_factory=list)
    last_observable_state: Optional[ObservableState] = None
    decisions: list = field(default_factory=list)
    events: list = field(default_factory=list)
    stop_reason: Optional[str] = None
    selector: str = "latest_valid_fallback_predictor_not_ready"
    def mark_failure(self, reason):
        if reason not in self.failure_reasons:
            self.failure_reasons.append(reason)
        self.status = RequestStatus.FAILED
    @property
    def service_failure(self):
        if self.failure_reasons:
            return True
        return None if self.unknown_checks else False
