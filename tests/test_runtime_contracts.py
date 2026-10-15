from dataclasses import asdict
import pytest
from selection.executor import OfflineModel, UnifiedExecutor
from selection.schema import *
from selection.policies import FixedOrderPolicy
from selection.metrics import aggregate
from selection.cascade_adapter import CascadeRouterAdapter

NAMES = ["ship", "shore", "cloud"]
def models():
    return [OfflineModel(n, ModelLevel(n), 1, 2, q) for n,q in zip(NAMES,[.9,.5,.2])]
def execute(ms=None, policy=None, **kw):
    return UnifiedExecutor(ms or models(), kw.pop("deadline",100), kw.pop("budget",100), .8,
                           policy=policy or FixedOrderPolicy(NAMES), **kw).execute({"task_id":"t", "question":"q", "evidence":"e"})

class Sequence:
    def __init__(self, names): self.names=iter(names)
    def decide(self, state): return ActionDecision(ActionType.CALL,next(self.names))

@pytest.mark.parametrize("seq", [["ship","ship"],["cloud","ship"],["shore","ship"],["unknown"]])
def test_actual_execute_rejects_bad_actions(seq):
    with pytest.raises(ValueError): execute(policy=Sequence(seq))

def test_level_not_input_order_and_skip():
    ms=models()[::-1]
    t=execute(ms, FixedOrderPolicy(["shore","cloud"]))
    assert [c.model_name for c in t.model_calls]==["shore","cloud"]
    t=execute(policy=FixedOrderPolicy(["ship","cloud"]))
    assert len(t.model_calls)==2
    with pytest.raises(ValueError): execute(policy=Sequence(["ship","cloud"]),allow_skip_levels=False)

def test_labels_cannot_change_decisions_or_answer():
    a=execute(); ms=models()
    for m in ms: m.quality=1-m.quality
    b=execute(ms)
    assert a.decisions==b.decisions and a.final_answer==b.final_answer=="cloud-answer"
    assert a.final_quality!=b.final_quality
    assert "hidden" not in repr(asdict(a.last_observable_state))
    assert a.last_observable_state.current_best_quality is None

def test_policy_sees_only_called_answers_and_original_input():
    seen=[]
    class Spy(FixedOrderPolicy):
        def decide(self,s):
            seen.append(asdict(s));return super().decide(s)
    ms=models()
    for m in ms:
        original=m.call
        def call(q,e,original=original):
            assert (q,e)==("q","e");return original(q,e)
        m.call=call
    execute(ms,Spy(NAMES))
    assert seen[0]["successful_models"]=={}
    assert list(seen[1]["successful_models"])==["ship"]
    assert not any(k.startswith("hidden") for s in seen for k in s)

def test_exact_accounting_includes_terminal_decision():
    t=execute(decision_overhead=.1,decision_cost=.2)
    assert t.total_time==pytest.approx(3.4)
    assert t.total_cost==pytest.approx(6.8)
    assert t.decision_time==pytest.approx(.4)

def test_failed_invalid_unavailable_and_unattempted():
    ms=models();ms[0].fail_probability=1;ms[1].invalid_after_answer=True
    t=execute(ms)
    assert [c.status for c in t.model_calls]==[ModelStatus.FAILED,ModelStatus.INVALID,ModelStatus.SUCCESS]
    assert t.total_cost==6 and t.total_time==3
    ms[2].available=False
    t=execute(ms)
    assert len(t.model_calls)==2 and t.final_answer is None
    assert "cloud" not in t.last_observable_state.attempted_models
    assert t.service_failure

def test_all_failed_and_empty_accept():
    ms=models()
    for m in ms:m.fail_probability=1
    t=execute(ms)
    assert len(t.model_calls)==3 and ServiceFailureReason.NO_VALID_ANSWER in t.failure_reasons
    t=execute(policy=FixedOrderPolicy([]))
    assert t.service_failure and t.cumulative_calls==0

def test_union_low_quality_timeout_budget():
    t=execute(deadline=.5,budget=1)
    assert t.total_time==1 and t.total_cost==2
    assert {ServiceFailureReason.TIMEOUT,ServiceFailureReason.BUDGET_EXCEEDED} <= set(t.failure_reasons)
    assert execute().failure_reasons==[ServiceFailureReason.LOW_QUALITY]

def test_decision_timeout_before_any_call():
    t=execute(deadline=.05,decision_overhead=.1)
    assert t.cumulative_calls==0 and t.total_time==.1
    assert ServiceFailureReason.TIMEOUT in t.failure_reasons
    assert ServiceFailureReason.NO_VALID_ANSWER in t.failure_reasons

@pytest.mark.parametrize("field",["quality","latency","cost"])
def test_missing_is_not_zero(field):
    ms=models();setattr(ms[0],field,None)
    t=execute(ms,FixedOrderPolicy(["ship"]))
    assert t.service_failure is None
    assert aggregate([t])["service_failure_rate"] is None
    assert aggregate([t])["failure_rate_upper"]==1

def test_exception_no_retry_unknown_bill():
    ms=models();attempts=[]
    def fail(q,e): attempts.append(1);raise RuntimeError("provider error")
    ms[0].call=fail
    t=execute(ms)
    assert len(attempts)==1 and t.total_cost is None
    assert t.cumulative_calls==1 and t.service_failure

def test_original_empty_guard_never_predicts():
    from selection.cascade_router import CascadeRouter
    class NotReady:
        def predict(self,*a):raise AssertionError("unfitted estimator accessed")
    r=CascadeRouter(NotReady(),NotReady(),NAMES,100,strategies=[])
    assert r.select_answer(["q"],[[None]*3])==[None]

def adapter(qualities=None):
    return CascadeRouterAdapter.fit_development_means(NAMES, qualities or [[.4,.7,.9],[.5,.6,.95]], [[1,2,3],[1,2,3]])

def test_original_adapter_runs_predict_and_select():
    p=adapter();t=execute(policy=p)
    assert p.predict_calls>=1 and len(t.model_calls)>=1
    assert t.final_answer is not None and t.selector=="policy_predictor"
    assert t.decisions[0].reason=="original_cascade_router_predict"

def test_original_adapter_failed_history_and_permissions():
    p=adapter();ms=models()
    for m in ms:m.fail_probability=1
    t=execute(ms,p)
    assert t.service_failure and len(t.model_calls)<=3
    t=UnifiedExecutor(models(),100,100,.8,policy=adapter()).execute({"allowed_models":["shore"],"question":"q"})
    assert [c.model_name for c in t.model_calls]==["shore"]

def test_original_adapter_initially_calls_even_when_best_is_first():
    p=CascadeRouterAdapter.fit_development_means(NAMES, [[.99,.5,.4],[.98,.6,.3]], [[1,2,3],[1,2,3]], max_expected_cost=1)
    t=execute(policy=p)
    assert [c.model_name for c in t.model_calls]==["ship"]


def test_exact_resource_boundary_and_measured_control():
    t=execute(policy=FixedOrderPolicy(["ship"]),deadline=1,budget=2)
    assert not t.service_failure
    t=execute(policy=FixedOrderPolicy(["ship"]),decision_timing="measured",decision_overhead=999)
    assert t.total_time==pytest.approx(1+t.measured_controller_time)
    assert t.decision_time==t.measured_controller_time

def test_unavailable_initial_model_is_not_attempted():
    ms=models();ms[0].available=False
    t=execute(ms)
    assert [c.model_name for c in t.model_calls]==["shore","cloud"]

def test_original_adapter_continues_after_failed_attempt():
    p=CascadeRouterAdapter.fit_development_means(NAMES,[[.99,.8,.7]],[[1,2,3]],max_expected_cost=1)
    ms=models();ms[0].fail_probability=1
    t=execute(ms,p)
    assert [c.model_name for c in t.model_calls][:2]==["ship","shore"]
    assert p.predict_calls>=2

def test_invalid_replay_keeps_null_answer():
    m=OfflineModel("ship",ModelLevel.SHIP,1,2,invalid_after_answer=True,use_default_answer=False,replay_reason="format_error")
    t=execute([m],FixedOrderPolicy(["ship"]))
    assert t.model_calls[0].answer is None and t.model_calls[0].reason=="format_error"
