from dataclasses import replace
from selection.v5.planner_policy import PlannerPolicy,JointLibraryProvider
from selection.v5.planner import PlanningState
from selection.v5.demo_planner import provider
from selection.v5.demo_planner_runtime import FixtureScorer
from selection.executor import UnifiedExecutor,OfflineModel
from selection.schema import ModelLevel,ObservableState,ActionType

def execute(labels):
    p=PlannerPolicy(FixtureScorer(),lambda q,e:provider,timeout_s=1)
    ms=[OfflineModel(n,ModelLevel(n),1,c,response_text=n) for n,c in [('ship',.01),('shore',.01),('cloud',.5)]]
    t=UnifiedExecutor(ms,12,1.5,.8,policy=p,decision_timing='measured').execute({'question':'original','evidence':'fixed'},evaluation_labels=labels)
    return t,p

def test_real_feedback_replanning_and_time_ledger():
    t,p=execute({'ship':.5,'shore':1,'cloud':.8})
    assert [c.model_name for c in t.model_calls]==['ship','shore']
    assert [x['action'] for x in p.plans]==['CALL:ship','CALL:shore','ACCEPT']
    assert abs(t.total_time-2-t.decision_time)<1e-9 and t.decision_time>0

def test_labels_do_not_change_actions():
    a,_=execute({'ship':1,'shore':0,'cloud':1});b,_=execute({'ship':0,'shore':1,'cloud':0})
    assert [d.model_name for d in a.decisions]==[d.model_name for d in b.decisions]
    assert a.final_model==b.final_model=='shore'

def test_unknown_service_probability_not_replaced_with_proxy():
    class Scorer:
        threshold=.8
        def predict(self,rows):return [{'predicted_quality':1,'service_pass_probability':None,'proxy_score_pass_probability':1} for _ in rows]
    p=PlannerPolicy(Scorer(),lambda q,e:lambda s,a:[])
    s=ObservableState('q','e',[],successful_models={'ship':'answer'},remaining_time=10,remaining_budget=1,deadline=12,budget=1.5)
    assert p.decide(s).action_type==ActionType.FAIL

def test_joint_bridge_hides_donor_identity():
    class Lib:
        def sample(self,*a):return {'supported':True,'scenarios':[{'weight':1,'donor_record_id':'secret-source','outcome':{'latency_s':1,'cost':.1}}]}
    seen=[]
    def mapper(s,a,o):
        seen.append(o)
        return replace(s,history=((a,'SUCCESS'),),remaining_time=s.remaining_time-1,remaining_cost=s.remaining_cost-.1)
    f=JointLibraryProvider(Lib(),lambda s,a:{},mapper,'request')
    assert len(f(PlanningState(),'ship'))==1 and 'donor_record_id' not in seen[0]

def test_joint_bridge_rejects_unsupported_mapping():
    class Lib:
        def sample(self,*a):return {'supported':True,'scenarios':[{'weight':1,'outcome':{'latency_s':1,'cost':.1}}]}
    f=JointLibraryProvider(Lib(),lambda s,a:{},lambda s,a,o:None,'r')
    assert f(PlanningState(),'ship')==[]
