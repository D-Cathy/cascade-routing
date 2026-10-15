from dataclasses import asdict

def summarize_trace(trace):
    result = {k:v for k,v in asdict(trace).items() if k not in {"events", "last_observable_state", "model_calls", "decisions", "question", "evidence"}}
    result["status"] = trace.status.value
    result["failure_reasons"] = [r.value for r in trace.failure_reasons]
    result["service_failure"] = trace.service_failure
    return result

def summarize_many(traces):
    return [summarize_trace(t) for t in traces]

def aggregate(traces):
    n = len(traces)
    if not n: raise ValueError("Empty evaluation")
    failed = sum(t.service_failure is True for t in traces)
    unknown = sum(t.service_failure is None for t in traces)
    def mean(field):
        values = [getattr(t,field) for t in traces]
        return None if any(v is None for v in values) else sum(values)/n
    return {"n_requests":n, "known_failures":failed, "unknown_outcomes":unknown,
            "service_failure_rate":None if unknown else failed/n,
            "failure_rate_lower":failed/n, "failure_rate_upper":(failed+unknown)/n,
            "mean_quality":mean("final_quality"), "mean_cost":mean("total_cost"),
            "mean_time":mean("total_time"), "valid_answer_rate":None if any(t.final_valid is None for t in traces) else sum(t.final_valid is True for t in traces)/n,
            "quality_observed_count":sum(t.final_quality is not None for t in traces),
            "cost_observed_count":sum(t.total_cost is not None for t in traces),
            "time_observed_count":sum(t.total_time is not None for t in traces),
            "risk_guarantee":False}


def evaluate_terminal(trace, quality_threshold, deadline, budget, labels=None, validities=None):
    """Evaluation only; does not invoke a policy or model or change the selected answer."""
    from .schema import RequestStatus, ServiceFailureReason
    trace.failure_reasons = []
    trace.unknown_checks = []
    trace.final_valid = trace.final_model is not None
    if trace.final_model is None:
        trace.final_quality = 0.0
        trace.mark_failure(ServiceFailureReason.NO_VALID_ANSWER)
    else:
        final_call = next(c for c in trace.model_calls if c.model_name == trace.final_model)
        trace.final_quality = labels.get(trace.final_model) if labels is not None else final_call.quality
        if validities is not None:
            trace.final_valid = validities.get(trace.final_model)
            if trace.final_valid is False:
                trace.final_quality = 0.0
                trace.mark_failure(ServiceFailureReason.NO_VALID_ANSWER)
            elif trace.final_valid is None:
                trace.unknown_checks.append("evaluated_validity")
    if trace.final_quality is None:trace.unknown_checks.append("quality")
    elif trace.final_quality < quality_threshold:trace.mark_failure(ServiceFailureReason.LOW_QUALITY)
    if trace.known_time > deadline:trace.mark_failure(ServiceFailureReason.TIMEOUT)
    elif trace.total_time is None:trace.unknown_checks.append("time")
    if trace.known_cost > budget:trace.mark_failure(ServiceFailureReason.BUDGET_EXCEEDED)
    elif trace.total_cost is None:trace.unknown_checks.append("cost")
    if not trace.failure_reasons:
        trace.status = RequestStatus.INDETERMINATE if trace.unknown_checks else RequestStatus.SUCCEEDED
    return trace
