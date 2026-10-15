"""Train/evaluate a small DEVELOPMENT scorer. Not a formal D_Q training entry."""
import argparse
import json
from pathlib import Path
import numpy as np
from ..routerbench_adapter import validate,digest,MODELS
from ..replay_data import load_dataset
from .scorers import ProxyScorer,load_scorer
from .splits import audit

def observations(data,split):
    rows=[];ys=[];keys=[]
    for t in data.tasks:
        if t['split']!=split:continue
        for name in t['allowed_models']:
            c=data.calls[(t['task_id'],name)];label=data.labels[(t['task_id'],name)]
            if c['status']!='SUCCESS' or label['quality'] is None:raise ValueError('Development fit/eval needs observed answers and proxy scores; no silent outcome filtering')
            rows.append(dict(question=t['question'],evidence=t['evidence'],answer=c['answer'],model_name=name))
            ys.append(label['quality']);keys.append([t['task_id'],name])
    return rows,ys,keys

def run(dataset,output):
    p=Path(dataset);validate(p)
    data=load_dataset(*(p/n for n in ['tasks.jsonl','calls.jsonl','labels.jsonl']),list(MODELS))
    if not 10<=len(data.tasks)<=20:raise ValueError('Development scorer supports 10–20 tasks only')
    # Independent audit: related fit/eval records must not cross the boundary.
    checked=[dict(schema_version=2,task_id=t['task_id'],source_group_id=t['source_group_id'],source_id='routerbench',
        source_sample_id=t['metadata']['sample_id'],template_family=None,category=t['metadata']['eval_name'],
        question=t['question'],evidence=t['evidence'],allowed_models=t['allowed_models'],
        split='D_Q' if t['split']=='dev_fit' else 'D_T',provenance='engineering_audit_only') for t in data.tasks]
    audit(checked) # In-memory boundary check only; no formal split is written.
    train,y,trainkeys=observations(data,'dev_fit')
    test,yt,testkeys=observations(data,'dev_eval')
    if not train or not test:raise ValueError('Separate development fit/eval required')
    scorer=ProxyScorer().fit(train,y)
    scorer.save(output,{'mode':'development_proxy_only','model_mapping':MODELS,
        'training_pairs':trainkeys,'evaluation_pairs':testkeys,
        'input_sha256':{str(p/n):digest(p/n) for n in ['tasks.jsonl','calls.jsonl','labels.jsonl','manifest.json']}})
    frozen,_=load_scorer(output);pred=frozen.predict(test)
    q=np.array([x['predicted_quality'] for x in pred]);prob=np.array([x['proxy_score_pass_probability'] for x in pred]);truth=np.array(yt)
    report={'fit_tasks':len({k[0] for k in trainkeys}),'fit_pairs':len(trainkeys),'eval_tasks':len({k[0] for k in testkeys}),
        'eval_pairs':len(testkeys),'quality_mae':float(np.mean(abs(q-truth))),
        'proxy_brier':float(np.mean((prob-(truth>=.8))**2)),
        'training_mean_baseline_mae':float(np.mean(abs(np.mean(y)-truth))),
        'service_probability_available':False,'formal_result':False,'model_calls':0}
    out=Path(output)
    (out/'evaluation.json').write_text(json.dumps(report,indent=2)+'\n')
    (out/'predictions.jsonl').write_text(''.join(json.dumps({'task_id':k[0],'model_name':k[1],**pr,'reference_proxy_quality':target})+'\n' for k,pr,target in zip(testkeys,pred,yt)))
    print(json.dumps(report));return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',required=True);p.add_argument('--output',required=True);a=p.parse_args();run(a.dataset,a.output)

if __name__=='__main__':main()
