"""Engineering-only cached-response replay under explicit time-indexed links."""
import argparse
import json
from dataclasses import asdict
from pathlib import Path
from .routerbench_adapter import validate, digest
from .replay_data import fields, number, load_dataset
from .resource_simulation import LinkTimeline, SimulatedCachedModel
from .executor import UnifiedExecutor
from .policies import FixedOrderPolicy
from .metrics import evaluate_terminal, aggregate

ORDERS={'fixed_ship':['ship'],'fixed_shore':['shore'],'fixed_cloud':['cloud'],
        'fixed_cascade_fallback':['ship','shore','cloud']}

def load(path):
    path=Path(path).resolve();cfg=json.loads(path.read_text())
    fields(cfg,['schema_version','purpose','dataset','seed','deadline_s','budget','quality_threshold',
                'decision_overhead_s','decision_cost','call_timeout_s','failure_detection_s','cancellation_s',
                'fee_reference','byte_reference','fee_weight','models','regimes'])
    if cfg['schema_version']!=1 or cfg['purpose']!='engineering_simulation_only' or type(cfg['seed']) is not int:
        raise ValueError('Unsupported simulation protocol')
    for k in ['deadline_s','budget','decision_overhead_s','decision_cost','call_timeout_s','failure_detection_s','cancellation_s','fee_reference','byte_reference']:
        number(cfg[k],k)
    for k in ['call_timeout_s','fee_reference','byte_reference']:
        if cfg[k]<=0:raise ValueError('Positive '+k+' required')
    for k in ['quality_threshold','fee_weight']:number(cfg[k],k,maximum=1)
    fields(cfg['models'],['ship','shore','cloud'])
    for spec in cfg['models'].values():
        fields(spec,['base_compute_s','seconds_per_output_byte','queue_max_s','fee_per_compute_s'])
        for k,v in spec.items():number(v,k)
    fields(cfg['regimes'],['normal','restricted','interrupted'])
    for segments in cfg['regimes'].values():
        if not isinstance(segments,list) or not segments:raise ValueError('Empty timeline')
        previous=-1
        for s in segments:
            fields(s,['at_s','bandwidth_mbps','one_way_latency_s'])
            for k,v in s.items():number(v,k)
            if s['at_s']<=previous:raise ValueError('Timeline must be strictly increasing')
            previous=s['at_s']
        if segments[0]['at_s']!=0:raise ValueError('Timeline must start at zero')
    directory=path.parent/cfg['dataset'];validate(directory)
    d=load_dataset(*(directory/n for n in ['tasks.jsonl','calls.jsonl','labels.jsonl']),list(cfg['models']))
    if not 10<=len(d.tasks)<=20:raise ValueError('Only 10–20 development tasks allowed')
    if any(c['status'] not in {'SUCCESS','INVALID'} for c in d.calls.values()):
        raise ValueError('Need collected answer caches; cannot simulate missing/failed historical answers')
    return cfg,d,directory

def run(path,output,scorer_path=None):
    cfg,data,directory=load(path)
    output=Path(output)
    if output.exists():raise FileExistsError('Use a new output directory')
    traces=[];summaries={};orders=dict(ORDERS);scorer=None
    if scorer_path:
        from .v5.scorers import load_scorer
        from .v5.selector import PredictedThresholdProxy
        from .routerbench_adapter import MODELS
        scorer,scorer_manifest=load_scorer(scorer_path)
        if scorer_manifest.get('mode')!='development_proxy_only' or scorer_manifest.get('model_mapping')!=MODELS:
            raise ValueError('Scorer provenance/model mapping mismatch')
        if scorer.threshold!=cfg['quality_threshold']:raise ValueError('Frozen scorer threshold mismatch')
        orders['predicted_threshold_proxy']=['ship','shore','cloud']
    for regime,segments in cfg['regimes'].items():
        timeline=LinkTimeline(regime,segments)
        for policy,order in orders.items():
            collected=[]
            for task in data.tasks:
                models=[SimulatedCachedModel(n,data.calls[(task['task_id'],n)],task['task_id'],cfg,timeline) for n in cfg['models']]
                executor=UnifiedExecutor(models,cfg['deadline_s'],cfg['budget'],cfg['quality_threshold'],
                    decision_overhead=cfg['decision_overhead_s'],decision_cost=cfg['decision_cost'],
                    policy=PredictedThresholdProxy(scorer) if policy=='predicted_threshold_proxy' else FixedOrderPolicy(order),environment_observer=timeline.observe)
                public={k:task[k] for k in ['task_id','source_group_id','question','evidence','allowed_models']}
                trace=executor.execute(public)
                # Labels never enter policy state or simulation; read after termination.
                labels={n:data.labels[(task['task_id'],n)]['quality'] for n in cfg['models']}
                validities={n:data.labels[(task['task_id'],n)]['valid'] for n in cfg['models']}
                evaluate_terminal(trace,cfg['quality_threshold'],cfg['deadline_s'],cfg['budget'],labels,validities)
                assert abs(trace.total_time-(trace.decision_time+sum(c.latency for c in trace.model_calls)))<1e-7
                assert abs(trace.total_cost-(len(trace.decisions)*cfg['decision_cost']+sum(c.cost for c in trace.model_calls)))<1e-7
                collected.append(trace)
                traces.append({**asdict(trace),'policy':policy,'regime':regime,'split':task['split'],
                               'service_failure':trace.service_failure,'resource_source':'simulated'})
            summaries[regime+'/'+policy]=aggregate(collected)
    output.mkdir(parents=True)
    def dump(name,value): (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    with (output/'traces.jsonl').open('w') as f:
        for t in traces:f.write(json.dumps(t,ensure_ascii=False,allow_nan=False)+'\n')
    dump('summary.json',summaries)
    dump('manifest.json',{'config':cfg,'tasks':len(data.tasks),'traces':len(traces),
        'input_sha256':{str(p.resolve()):digest(p) for p in [Path(path),*(directory/n for n in ['manifest.json','tasks.jsonl','calls.jsonl','labels.jsonl'])]},
        'code_sha256':{n:digest(Path(__file__).parent/n) for n in ['simulation_replay.py','resource_simulation.py','executor.py','policies.py','metrics.py']},
        'model_calls_executed':0,'risk_guarantee':False,'formal_experiment':False,
        'scorer_path':str(scorer_path) if scorer_path else None,
        'scorer_sha256':digest(Path(scorer_path)/'scorer.joblib') if scorer_path else None,
        'cost_unit':'simulated_normalized_fee_and_bytes','quality_source':'routerbench_proxy',
        'validity_source':'missing_preserved','all_tasks_used_for':'engineering_smoke_test_not_heldout_performance',
        'limitations':['Optional scorer is a development proxy, not paper encoder/service classifier; no calibrated v5 planner; fallback is not threshold baseline',
            'Cache score retained only for completed unchanged answers; interrupted calls expose no answer',
            'No verified v5 validity; full failure rate can remain null',
            'Compute time modeled by UTF-8 answer byte count, not measured latency or actual tokens',
            'Queue is task-role seeded exogenous delay, not an endogenous shared-server queue',
            'Fee rates/reference scales are explicit engineering assumptions; original cache costs not charged',
            'Link outage detected at communication; no mid-compute link cancellation',
            'Per-call timeout plus cancellation; request deadline checked at decision boundaries, not hard cancellation',
            'Actual local controller wall time recorded diagnostically, not added to simulated totals']})
    result={'status':'completed','tasks':len(data.tasks),'regimes':len(cfg['regimes']),
            'policies':len(orders),'traces':len(traces),'model_calls_executed':0,'risk_guarantee':False}
    print(json.dumps(result));return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True)
    p.add_argument('--output');p.add_argument('--scorer');p.add_argument('--validate-only',action='store_true');a=p.parse_args()
    if a.validate_only:
        cfg,data,_=load(a.config);print(json.dumps({'valid':True,'tasks':len(data.tasks),'regimes':len(cfg['regimes']),'resource_source':'simulated'}));return
    if not a.output:p.error('--output required')
    run(a.config,a.output,a.scorer)

if __name__=='__main__':main()
