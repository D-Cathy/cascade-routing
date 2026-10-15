from dataclasses import replace
import time
import pytest
from selection.v5.planner import PlanningState,Scenario,FinitePlanner,Candidate,pareto

def child(s,m,q=.9,p=.99,t=1,c=.1,status='SUCCESS'):
    return replace(s,history=s.history+((m,status),),remaining_time=s.remaining_time-t,remaining_cost=s.remaining_cost-c,quality=q,pass_probability=p,has_answer=True)

def test_direct_cloud_and_vector():
    def provider(s,m):return [Scenario(1,child(s,m),1,.1)] if m=='cloud' else []
    r=FinitePlanner(provider).plan(PlanningState())
    assert r['action']=='CALL:cloud' and r['vector']==pytest.approx((.1,1,.1,.01))

def test_accept_without_future_calls():
    s=PlanningState(quality=.95,pass_probability=.99,has_answer=True)
    assert FinitePlanner(lambda s,m:[]).plan(s)['action']=='ACCEPT'

def test_unknown_probability_no_false_accept():
    s=PlanningState(quality=1,has_answer=True)
    assert FinitePlanner(lambda s,m:[]).plan(s)['action']=='FAIL'

def test_failed_model_cannot_retry():
    seen=[]
    def provider(s,m):seen.append(m);return []
    FinitePlanner(provider).plan(PlanningState(history=(('shore','FAILED'),)))
    assert seen==['cloud']

def test_weighted_branches_hand_calculation():
    def provider(s,m):
        if m!='cloud':return []
        return [Scenario(.25,child(s,m,q=.8,p=.9,t=1,c=.1),1,.1),Scenario(.75,child(s,m,q=1,p=1,t=2,c=.2),2,.2)]
    r=FinitePlanner(provider).plan(PlanningState())
    assert r['vector']==pytest.approx((.05,1.75,.175,.025))

def test_duplicate_observations_shared_continuation():
    def provider(s,m):
        if m!='cloud':return []
        ch=child(s,m)
        return [Scenario(.5,ch,1,.1),Scenario(.5,ch,1,.1)]
    r=FinitePlanner(provider).plan(PlanningState())
    assert len(r['continuation'])==2 and r['vector']==pytest.approx((.1,1,.1,.01))

def test_ledger_mismatch_rejected():
    with pytest.raises(ValueError,match='ledger'):
        FinitePlanner(lambda s,m:[Scenario(1,child(s,m,t=2),1,.1)]).plan(PlanningState())

def test_weight_error_rejected():
    with pytest.raises(ValueError,match='weights'):
        FinitePlanner(lambda s,m:[Scenario(.5,child(s,m),1,.1)]).plan(PlanningState())

def test_dominated_removed():
    rows=[Candidate((.1,1,.1,.01),'A',{}),Candidate((.2,2,.2,.02),'B',{})]
    assert [c.action for c in pareto(rows)]==['A']

def test_timeout_fallback():
    def provider(s,m):time.sleep(.003);return []
    r=FinitePlanner(provider,timeout_s=.001).plan(PlanningState())
    assert r['action']=='FAIL' and r['reason']=='planning_timeout'

def test_two_step_better_than_direct():
    def provider(s,m):
        if not s.history and m=='ship':return [Scenario(1,child(s,m,q=.5,p=.5,c=.01),1,.01)]
        if s.history and m=='shore':return [Scenario(1,child(s,m,q=1,p=1,c=.01),1,.01)]
        if not s.history and m=='cloud':return [Scenario(1,child(s,m,q=.8,p=.95,c=.5),1,.5)]
        return []
    r=FinitePlanner(provider,timeout_s=1).plan(PlanningState())
    assert r['action']=='CALL:ship' and r['vector']==pytest.approx((0,2,.02,0))

def test_zero_budget_no_free_call():
    def provider(s,m):return [Scenario(1,replace(child(replace(s,remaining_cost=1),m),remaining_cost=0),1,.1)]
    assert FinitePlanner(provider).plan(PlanningState(remaining_cost=0))['action']=='FAIL'

def test_permissions_and_state_identity():
    a=PlanningState();b=replace(a,remaining_time=11.999999)
    assert a.key()!=b.key()
    with pytest.raises(ValueError):PlanningState(history=(('cloud','SUCCESS'),('ship','SUCCESS')))

def test_grid_cap_retains_real_vector():
    def provider(s,m):return [Scenario(1,child(s,m,q=.9,p=.99),1,.1)]
    r=FinitePlanner(provider,epsilon=.02,max_front=1,timeout_s=1).plan(PlanningState())
    assert r['frontier_size']==1 and r['vector']==pytest.approx((.1,1,.1,.01))
