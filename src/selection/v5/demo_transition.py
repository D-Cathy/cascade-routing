"""12 synthetic source groups exercise step 5; no RouterBench eval reuse."""
import argparse
import json
from pathlib import Path
import joblib
from ..schema import ObservableState,ModelCallRecord,ModelStatus
from ..routerbench_adapter import write_rows,digest
from .selector import PredictedThresholdProxy
from .history import build_transition
from .gain import GainModels,ROLES
from .transition_library import JointTransitionLibrary,public_transition

class FixtureScorer:
    threshold=.8
    def predict(self,rows):
        return [{'predicted_quality':float(r['answer'])} for r in rows]

def run(output):
    out=Path(output)
    if out.exists():raise FileExistsError('Use a new output directory')
    selector=PredictedThresholdProxy(FixtureScorer());rows=[]
    # Each source supplies same history/action with varied, jointly coupled outcomes.
    for i in range(12):
        state=ObservableState('Synthetic fixture','Fixed evidence',['shore','cloud'],
            attempted_models={'ship':ModelStatus.SUCCESS},successful_models={'ship':'.4'},
            remaining_time=10+i*.01,remaining_budget=1.5,environment={'bandwidth_mbps':1.0})
        call=ModelCallRecord('shore','shore',ModelStatus.SUCCESS,1+i*.1,.1+i*.01,answer='.7')
        rows.append(build_transition(f'fixture-{i}',f'synthetic-group-{i}',state,call,selector,
                                     {'ship':.8,'shore':.3 if i%2 else 1.0},{'bandwidth_mbps':1.0}))
    train=rows[:8];query_rows=rows[8:]
    gains=GainModels().fit(train)
    library_rows=[]
    for r in train:
        public=public_transition(r);public['gains']=gains.predict(r['features'],['shore','cloud'])['gain_vector'];library_rows.append(public)
    library=JointTransitionLibrary(library_rows,min_groups=5,max_distance=10.0)
    queries=[]
    for r in query_rows:
        q={k:r[k] for k in ['action','history','features']};q['gains']=gains.predict(r['features'],['shore','cloud'])['gain_vector']
        queries.append({'record_id':r['record_id'],'result':library.sample(q,r['record_id'])})
    out.mkdir(parents=True);(out/'private').mkdir()
    write_rows(out/'private/training_transitions.jsonl',train)
    write_rows(out/'library.jsonl',library_rows);write_rows(out/'queries.jsonl',queries)
    (out/'retrieval_config.json').write_text(json.dumps({'kappa':1.0,'min_groups':5,'max_groups':20,
        'max_distance':10.0,'threshold_source':'synthetic_engineering_constant_not_D_V',
        'base_scale':library.base_scale.tolist(),'gain_scale':library.gain_scale.tolist(),
        'kernel':'engineering_Gaussian','seed':20261014},indent=2)+'\n')
    joblib.dump(gains,out/'gain_models.joblib')
    restored=joblib.load(out/'gain_models.joblib')
    assert restored.predict(train[0]['features'],['shore'])==gains.predict(train[0]['features'],['shore'])
    report={'mode':'synthetic_unit_integration_demo','source_groups':12,'fit_groups':8,'query_groups':4,
        'negative_targets':sum(r['gain_target']<0 for r in train),
        'supported_queries':sum(q['result']['supported'] for q in queries),
        'formal_D_G_used':False,'routerbench_eval_reused':False,'risk_guarantee':False,'model_calls':0,
        'limitations':['fixture scorer, synthetic labels and resources only','no planner or proxy-state mapping',
        'fixed engineering distance threshold, not D_V quantile','reduced nine-dimensional features, no task embedding',
        'Gaussian engineering kernel, not verified paper Eq 3.12','post-environment held fixed in fixture',
        'no formal trained scorer or dynamics experiment'],
        'artifact_sha256':{str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}}
    (out/'manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report));return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);a=p.parse_args();run(a.output)

if __name__=='__main__':main()
