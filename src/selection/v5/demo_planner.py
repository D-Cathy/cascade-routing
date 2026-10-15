"""Hand-computable microtree demonstration; not a learned transition experiment."""
import argparse
import json
from dataclasses import replace
from pathlib import Path
from .planner import PlanningState,Scenario,FinitePlanner

def provider(s,action):
    if not s.history and action=='ship':q,p,t,c=.5,.5,1.,.01
    elif s.history and action=='shore':q,p,t,c=1.,1.,1.,.01
    elif not s.history and action=='cloud':q,p,t,c=.8,.95,1.,.5
    else:return []
    child=replace(s,history=s.history+((action,'SUCCESS'),),remaining_time=s.remaining_time-t,
                  remaining_cost=s.remaining_cost-c,quality=q,pass_probability=p,has_answer=True)
    return [Scenario(1.,child,t,c)]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args()
    out=Path(a.output)
    if out.exists():raise FileExistsError('Use a new output directory')
    state=PlanningState();planner=FinitePlanner(provider,timeout_s=1);steps=[]
    for _ in range(4):
        result=planner.plan(state);steps.append(result)
        if not result['action'].startswith('CALL:'):break
        state=provider(state,result['action'][5:])[0].state
    expected=['CALL:ship','CALL:shore','ACCEPT']
    assert [s['action'] for s in steps]==expected
    out.mkdir(parents=True)
    result={'mode':'synthetic_hand_tree_only','steps':steps,'expected_actions':expected,
            'model_calls':0,'formal_v5_planner':False,'risk_guarantee':False,
            'limitations':['no learned donor-to-state adapter','no runtime policy integration','no complete paper baselines',
                            'root-only Pareto/grid; exhaustive internal policies','demo timeout 1s, not production 50ms',
                            'predicted fixture probabilities; no calibrated service classifier']}
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'actions':expected,'initial_vector':steps[0]['vector'],'model_calls':0}))

if __name__=='__main__':main()
