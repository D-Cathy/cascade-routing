from __future__ import annotations
import math
import time
from dataclasses import dataclass
from copy import deepcopy
from .schema import (ActionDecision, ActionType, CallNotStartedError, ModelCallRecord, ModelLevel,
                     ModelStatus, ObservableState, RequestStatus, ServiceFailureReason, TraceRecord)

@dataclass
class OfflineModel:
    """Deterministic diagnostic replay; latency/cost are supplied, never wall-clock added."""
    name: str
    level: ModelLevel
    latency: float | None
    cost: float | None
    quality: float | None = None
    fail_probability: float = 0.0  # compatibility: only deterministic 0 or 1 accepted
    invalid_after_answer: bool = False
    available: bool = True
    response_text: str | None = None
    model_version: str = "synthetic-v1"
    data_source: str = "synthetic"
    latency_source: str = "simulated"
    cost_source: str = "simulated"
    use_default_answer: bool = True
    replay_reason: str | None = None
    def __post_init__(self):
        if self.fail_probability not in (0, 1):
            raise ValueError("Use deterministic replay status; fractional failure probability unsupported")
        for value in (self.latency, self.cost):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("Resource must be finite nonnegative or None")
    def call(self, question, evidence):
        failed = not self.available or self.fail_probability == 1
        answer = None if failed else (self.response_text if self.response_text is not None or not self.use_default_answer else f"{self.name}-answer")
        status = ModelStatus.FAILED if failed else (ModelStatus.INVALID if self.invalid_after_answer or not isinstance(answer, str) or not answer.strip() else ModelStatus.SUCCESS)
        return ModelCallRecord(self.name, self.level.value, status, self.latency, self.cost,
                               answer, self.quality, self.replay_reason or ("unavailable" if not self.available else ("replay_failure" if failed else None)),
                               model_version=self.model_version, data_source=self.data_source,
                               latency_source=self.latency_source, cost_source=self.cost_source)

class UnifiedExecutor:
    """Unified serial replay/live executor. Labels are read only after termination.

    decision_timing=simulated uses the fixed overhead ONCE per decision (including
    terminal decisions). measured uses measured controller duration instead.
    execution_timing=wall_clock measures the whole live request once; component
    latencies are diagnostic and are not added to the wall-clock total.
    """
    def __init__(self, models, deadline, budget, quality_threshold, decision_overhead=0.0,
                 policy=None, allow_skip_levels=True, decision_timing="simulated", decision_cost=0.0, execution_timing="replay", environment_observer=None):
        if execution_timing not in {"replay", "wall_clock"} or (execution_timing == "wall_clock" and decision_timing != "measured"):
            raise ValueError("Wall-clock execution requires measured controller timing")
        self.execution_timing = execution_timing
        if environment_observer is not None and execution_timing != "replay":
            raise ValueError("Simulated environment observer requires replay timing")
        self.environment_observer = environment_observer
        self.models = {m.name: m for m in models}
        if len(self.models) != len(models):
            raise ValueError("Duplicate model names")
        for value in (deadline, budget, decision_overhead, decision_cost):
            if not math.isfinite(value) or value < 0:
                raise ValueError("Invalid service/control resource")
        if not 0 <= quality_threshold <= 1 or decision_timing not in {"simulated", "measured"}:
            raise ValueError("Invalid threshold/timing mode")
        self.deadline, self.budget, self.quality_threshold = deadline, budget, quality_threshold
        self.decision_overhead, self.decision_cost = decision_overhead, decision_cost
        self.policy, self.allow_skip_levels, self.decision_timing = policy, allow_skip_levels, decision_timing
    def _model_level_rank(self, name):
        return ModelLevel.order()[self.models[name].level.value]
    def _validate_call(self, state, candidate_model, requested_by=None):
        if candidate_model not in self.models:
            raise ValueError(f"Unknown model: {candidate_model}")
        if candidate_model in state.attempted_models:
            raise ValueError(f"Model already attempted: {candidate_model}")
        if candidate_model not in state.allowed_models:
            raise ValueError(f"Model not allowed: {candidate_model}")
        previous = list(state.attempted_models)
        if requested_by is not None:
            previous.append(requested_by)
        if previous:
            rank = max(self._model_level_rank(n) for n in previous)
            candidate_rank = self._model_level_rank(candidate_model)
            if candidate_rank <= rank:
                raise ValueError("Only strictly upward calls are allowed")
            if not self.allow_skip_levels and candidate_rank != rank + 1:
                raise ValueError("Skip-level calls forbidden")
    def _make_state(self, request, trace):
        allowed = list(request.get("allowed_models", self.models))
        if len(set(allowed)) != len(allowed) or any(n not in self.models for n in allowed):
            raise ValueError("Invalid allowed_models")
        attempted = {c.model_name: c.status for c in trace.model_calls}
        rank = max((self._model_level_rank(n) for n in attempted), default=-1)
        allowed = [n for n in allowed if n not in attempted and self._model_level_rank(n) > rank
                   and self.models[n].available and (self.allow_skip_levels or rank < 0 or self._model_level_rank(n) == rank + 1)]
        valid = {c.model_name:c.answer for c in trace.model_calls if c.status == ModelStatus.SUCCESS}
        state = ObservableState(question=request.get("question", ""), evidence=request.get("evidence", ""),
            allowed_models=allowed, attempted_models=attempted, successful_models=valid,
            failed_models={c.model_name:c.reason or "failed" for c in trace.model_calls if c.status == ModelStatus.FAILED},
            invalid_models={c.model_name:"invalid_answer" for c in trace.model_calls if c.status == ModelStatus.INVALID},
            remaining_time=None if trace.total_time is None else max(0, self.deadline-trace.total_time),
            remaining_budget=None if trace.total_cost is None else max(0, self.budget-trace.total_cost),
            quality_threshold=self.quality_threshold, deadline=self.deadline, budget=self.budget,
            environment=deepcopy(request.get("environment", {})))
        if self.environment_observer is not None and trace.total_time is not None:
            state.environment = deepcopy(self.environment_observer(trace.total_time))
        # Selector sees only completed valid answers, never labels or replay records.
        selected = next(reversed(valid), None)
        if self.policy is not None and hasattr(self.policy, "select_answer"):
            selected = self.policy.select_answer(deepcopy(state))
            trace.selector = "policy_predictor"
        if selected is not None and selected not in valid:
            raise ValueError("Selector returned an uncalled/invalid model")
        state.current_best_answer = valid.get(selected)
        if selected is not None and hasattr(self.policy, "estimate"):
            estimate = float(self.policy.estimate(deepcopy(state), selected))
            if not math.isfinite(estimate):
                raise ValueError("Nonfinite prediction")
            state.current_quality_estimate = state.current_best_quality = estimate
        return state, selected
    def _account(self, trace, latency, cost, known_cost=0.0):
        if latency is None:
            trace.total_time = None
        else:
            trace.known_time += latency
            if trace.total_time is not None: trace.total_time += latency
        if cost is None:
            trace.total_cost = None
            trace.known_cost += known_cost
        else:
            trace.known_cost += cost
            if trace.total_cost is not None: trace.total_cost += cost
    def _refresh_wall_time(self, trace, started):
        if self.execution_timing == "wall_clock":
            trace.total_time = trace.known_time = time.perf_counter() - started

    def execute(self, request, evaluation_labels=None):
        request_started = time.perf_counter()
        trace = TraceRecord(str(request.get("task_id", request.get("request_id", "anonymous"))),
                            request.get("question", ""), request.get("evidence", ""), request.get("source_group_id", "unspecified"))
        while True:
            self._refresh_wall_time(trace, request_started)
            start = time.perf_counter()
            state, selected = self._make_state(request, trace)
            trace.last_observable_state = deepcopy(state)
            trace.final_model, trace.final_answer = selected, state.current_best_answer
            # Unknown cumulative resource stops further expenditure, without calling it zero.
            if trace.known_time > self.deadline or trace.known_cost > self.budget:
                decision = ActionDecision(ActionType.ACCEPT, reason="resource_limit")
            elif trace.total_time is None or trace.total_cost is None:
                decision = ActionDecision(ActionType.ACCEPT, reason="unknown_resource_safe_stop")
            elif self.policy is None:
                next_name = next(iter(state.allowed_models), None)
                decision = ActionDecision(ActionType.CALL, next_name) if next_name else ActionDecision(ActionType.ACCEPT, reason="exhausted")
            else:
                decision = self.policy.decide(deepcopy(state))
            measured = time.perf_counter()-start
            charged = self.decision_overhead if self.decision_timing == "simulated" else measured
            trace.measured_controller_time += measured
            trace.decision_time += charged
            self._account(trace, charged, self.decision_cost)
            self._refresh_wall_time(trace, request_started)
            trace.decisions.append(decision)
            trace.events.append({"state":state.to_observable_dict(), "decision":deepcopy(decision),
                                 "charged_decision_time":charged, "total_time":trace.total_time, "total_cost":trace.total_cost})
            if trace.known_time > self.deadline or trace.known_cost > self.budget:
                trace.stop_reason = "resource_limit"
                break
            if decision.action_type in (ActionType.ACCEPT, ActionType.FAIL):
                trace.stop_reason = decision.reason or decision.action_type.value
                if decision.action_type == ActionType.FAIL:
                    trace.final_model = trace.final_answer = None
                break
            if decision.action_type != ActionType.CALL:
                raise ValueError("Unknown action")
            self._validate_call(state, decision.model_name)
            model = self.models[decision.model_name]
            call_started = time.perf_counter()
            try:
                if hasattr(model, "call_at"):
                    if self.execution_timing != "replay" or trace.total_time is None:
                        raise CallNotStartedError("Time-indexed simulator requires known replay time")
                    call = model.call_at(trace.question, trace.evidence, start_s=trace.total_time)
                elif hasattr(model, "call_with_context"):
                    if self.execution_timing != "wall_clock":
                        raise CallNotStartedError("Live backends require wall-clock execution")
                    remaining = self.deadline - (time.perf_counter() - request_started)
                    if remaining <= 0:
                        trace.stop_reason = "resource_limit"
                        break
                    call = model.call_with_context(trace.question, trace.evidence,
                                                   request_id=trace.request_id, timeout_s=remaining)
                else:
                    call = model.call(trace.question, trace.evidence)
            except CallNotStartedError:
                raise
            except Exception as exc:
                # No retry. Cannot infer provider charges or remote duration from an exception.
                call = ModelCallRecord(model.name, model.level.value, ModelStatus.FAILED,
                                       time.perf_counter()-call_started if self.execution_timing == "wall_clock" else None, None,
                                       reason=f"exception:{type(exc).__name__}",
                                       model_version=getattr(model,"model_version","unknown"),
                                       data_source=getattr(model,"data_source","synthetic"),
                                       latency_source="measured" if self.execution_timing == "wall_clock" else "missing", cost_source="missing")
            if call.model_name != model.name or call.level != model.level.value or call.status not in {ModelStatus.SUCCESS, ModelStatus.FAILED, ModelStatus.INVALID}:
                raise ValueError("Invalid backend record")
            for resource in (call.latency, call.cost, call.known_cost):
                if resource is not None and (not math.isfinite(resource) or resource < 0):
                    raise ValueError("Invalid backend resource")
            if call.status == ModelStatus.SUCCESS and (not isinstance(call.answer,str) or not call.answer.strip()):
                call.status = ModelStatus.INVALID
            trace.model_calls.append(call)
            trace.cumulative_calls += 1
            self._account(trace, call.latency, call.cost, call.known_cost)
            self._refresh_wall_time(trace, request_started)
            trace.events[-1]["call_index"] = trace.cumulative_calls-1
            trace.events[-1]["after_call_time"] = trace.total_time
            trace.events[-1]["after_call_cost"] = trace.total_cost
        self._refresh_wall_time(trace, request_started)
        from .metrics import evaluate_terminal
        return evaluate_terminal(trace, self.quality_threshold, self.deadline, self.budget, evaluation_labels)
