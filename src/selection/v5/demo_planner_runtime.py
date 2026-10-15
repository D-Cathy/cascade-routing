"""20 synthetic requests exercise real executor feedback with fixture planning."""
import argparse
import json
from dataclasses import asdict
from pathlib import Path
from .planner_policy import PlannerPolicy
from .demo_planner import provider
from ..executor import UnifiedExecutor,OfflineModel
from ..schema import ModelLevel
from ..routerbench_adapter import digest

class FixtureScorer:
    threshold=.8
    def predict(self,rows):
        values={'ship':(.5,.5),'shore':(1.,1.),'cloud':(.8,.95)}
        return [dict(predicted_quality=values[r['model_name']][0],service_pass_probability=values[r['model_name']][1]) for r in rows]

def run(output):
    out=Path(output)
    if out.exists():raise FileExistsError('Use a new output directory')
    rows=[];plans=[]
    for i in range(20):
        policy=PlannerPolicy(FixtureScorer(),lambda q,e:provider,timeout_s=1)
        models=[OfflineModel(n,ModelLevel(n),1.,c,response_text=n+' fixture answer',model_version='synthetic-fixture',use_default_answer=False)
                for n,c in [('ship',.01),('shore',.01),('cloud',.5)]]
        # Executor charges actual scoring/planning/control time once, separately from simulated calls.
        trace=UnifiedExecutor(models,12,1.5,.8,policy=policy,decision_timing='measured').execute(
            {'task_id':f'planner-fixture-{i}','question':'Synthetic test question','evidence':'Fixed synthetic evidence','environment':{'bandwidth_mbps':1.}},
            evaluation_labels={'ship':.5,'shore':1.,'cloud':.8})
        assert [c.model_name for c in trace.model_calls]==['ship','shore']
        assert abs(trace.total_time-2-trace.decision_time)<1e-9
        assert trace.final_model=='shore'
        rows.append(asdict(trace));plans.append(policy.plans)
    out.mkdir(parents=True)
    (out/'traces.jsonl').write_text(''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in rows))
    (out/'plans.json').write_text(json.dumps(plans,indent=2)+'\n')
    result={'mode':'synthetic_planner_executor_integration','tasks':20,'simulated_calls':40,'real_model_calls':0,
        'action_sequence':['ship','shore','ACCEPT'],'control_time':'measured_and_charged_once',
        'formal_v5_complete':False,'risk_guarantee':False,
        'limitations':['fixture transition/scorer, no learned current-task donor mapping',
        'root-only compression, not all paper baseline methods','future control overhead not modeled; actual control time charged',
        '1-second demo planning allowance, production budget not validated'],
        'output_sha256':{p.name:digest(p) for p in out.iterdir() if p.is_file()}}
    (out/'manifest.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args();run(a.output)
if __name__=='__main__':main()
