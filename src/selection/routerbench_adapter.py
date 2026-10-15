"""Offline RouterBench -> strict v1 DEVELOPMENT dataset. No model execution."""
import argparse
import ast
import csv
import hashlib
import json
import math
from pathlib import Path

from .replay_data import load_dataset

MODELS = {'ship': 'mistralai/mistral-7b-chat',
          'shore': 'mistralai/mixtral-8x7b-chat',
          'cloud': 'gpt-4-1106-preview'}

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()

def text_cell(value):
    """Accept text or serialized list of strings, never execute CSV content."""
    if not value or not value.strip(): return ''
    if value.lstrip().startswith('['):
        try: parts = ast.literal_eval(value)
        except (ValueError, SyntaxError) as exc: raise ValueError('Malformed text list') from exc
        if not isinstance(parts, list) or any(not isinstance(x, str) for x in parts):
            raise ValueError('Expected a list of strings')
        return '\n\n'.join(parts)
    return value

def numeric(value, maximum=None):
    if value is None or not value.strip(): return None
    v = float(value)
    if not math.isfinite(v) or v < 0 or (maximum is not None and v > maximum):
        raise ValueError('Invalid numeric value: '+str(value))
    return v

def write_rows(path, rows):
    path.write_text(''.join(json.dumps(r, ensure_ascii=False, allow_nan=False)+'\n' for r in rows), encoding='utf-8')

def validate(output):
    p = Path(output)
    d = load_dataset(p/'tasks.jsonl', p/'calls.jsonl', p/'labels.jsonl', list(MODELS))
    manifest = json.loads((p/'manifest.json').read_text())
    for name, sha in manifest['output_sha256'].items():
        if digest(p/name) != sha: raise ValueError('Artifact checksum mismatch: '+name)
    return {'tasks':len(d.tasks), 'calls':len(d.calls), 'labels':len(d.labels),
            'status':'validated', 'ready_for_resource_replay':False}

def convert(source, output, limit=20, seed=20261014):
    if not 10 <= limit <= 20: raise ValueError('Development export requires 10–20 tasks')
    source, out = Path(source), Path(output)
    if out.exists(): raise FileExistsError('Use a new output directory')
    required = ['sample_id','prompt','eval_name'] + [m+s for m in MODELS.values() for s in ['', '|model_response','|total_cost']]
    selected, seen = [], set()
    with source.open(encoding='utf-8', newline='') as f:
        reader=csv.DictReader(f)
        if set(required)-set(reader.fieldnames or []): raise ValueError('Missing required RouterBench columns')
        for line,row in enumerate(reader,2):
            sid=row['sample_id']
            if not sid or sid in seen: raise ValueError('Empty or duplicate sample_id')
            seen.add(sid)
            # Selection never depends on model answers, labels, or costs.
            rank=hashlib.sha256(f'{seed}:{sid}'.encode()).hexdigest()
            selected.append((rank,line,row));selected.sort(key=lambda x:x[0])
            del selected[limit:]
    if len(selected)!=limit: raise ValueError('Not enough source rows')
    # Conservative benchmark-family groups: no family can cross dev fit/eval.
    families=sorted({r['eval_name'] for _,_,r in selected},key=lambda s:hashlib.sha256(f'{seed}:{s}'.encode()).hexdigest())
    if len(families)<2 or any(not f for f in families): raise ValueError('Need at least two nonempty source families')
    splits={f:('dev_fit' if i%2==0 else 'dev_eval') for i,f in enumerate(families)}
    tasks,calls,labels=[],[],[]
    prompt_groups={}
    for _,line,row in selected:
        question=text_cell(row['prompt'])
        if not question.strip(): raise ValueError('Empty prompt')
        key=' '.join(question.casefold().split())
        family=row['eval_name']
        if key in prompt_groups and prompt_groups[key]!=family:
            raise ValueError('Duplicate prompt across source families; regroup before export')
        prompt_groups[key]=family
        tid='routerbench-0shot:'+row['sample_id']
        tasks.append(dict(schema_version=1,task_id=tid,source_group_id='routerbench-family:'+family,
            source='engineering_cache',split=splits[family],question=question,evidence='',
            allowed_models=list(MODELS),service=dict(quality_threshold=0.8,deadline_s=12,budget=1.5,
                cost_unit='routerbench_raw_cost_unverified',risk_target=0.1),environment={},
            metadata={'source_record':line,'sample_id':row['sample_id'],'eval_name':family,
                      'purpose':'development_adapter_only','budget_semantics':'placeholder_not_v5_normalized_cost'}))
        for role,model in MODELS.items():
            answer=text_cell(row[model+'|model_response'])
            cost=numeric(row[model+'|total_cost'])
            score=numeric(row[model],1)
            calls.append(dict(schema_version=1,task_id=tid,model_name=role,model_version=model,
                status='SUCCESS' if answer.strip() else 'INVALID',answer=answer or None,
                latency_s=None,cost=cost,latency_source='missing',cost_source='derived' if cost is not None else 'missing',
                data_source='engineering_cache',reason='cached_nonempty_text_only' if answer.strip() else 'empty_cached_answer_execution_status_unknown',
                metadata={'upstream_model_id':model,'validity_scope':'nonempty_text_only_not_v5_validity',
                          'cost_scope':'unmodified_upstream_total_cost_unit_unverified','historical_execution_status':'unknown'}))
            labels.append(dict(schema_version=1,task_id=tid,model_name=role,quality=score,valid=None,
                label_source='routerbench_proxy' if score is not None else 'missing',rubric_version='upstream_benchmark_not_v5'))
    # Validate before publishing any directory.
    from .replay_data import validate_tasks
    validate_tasks(tasks,list(MODELS))
    out.mkdir(parents=True)
    for name,rows in [('tasks',tasks),('calls',calls),('labels',labels)]: write_rows(out/(name+'.jsonl'),rows)
    manifest={'mode':'routerbench_development_adapter','source_path':str(source.resolve()),
        'source_sha256':digest(source),'source_rows_scanned':len(seen),'seed':seed,'tasks':len(tasks),
        'role_mapping':MODELS,'role_mapping_is_proxy':True,'source_group_rule':'whole_eval_name_family',
        'source_independence_verified':False,'near_duplicate_audit_complete':False,
        'selection_rule':'lowest seeded SHA256(sample_id), no outcome filtering',
        'formal_splits_created':False,'risk_guarantee':False,'model_calls_executed':0,
        'ready_for_resource_replay':False,'missing':['latency','v5_quality_labels','v5_validity','normalized_cost','formal_split_audit'],
        'output_sha256':{n:digest(out/n) for n in ['tasks.jsonl','calls.jsonl','labels.jsonl']}}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return validate(out)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--limit',type=int,default=20);p.add_argument('--seed',type=int,default=20261014)
    p.add_argument('--validate-only',action='store_true');a=p.parse_args()
    if not a.validate_only and a.source is None:p.error('--source is required for export')
    print(json.dumps(validate(a.output) if a.validate_only else convert(a.source,a.output,a.limit,a.seed),indent=2))

if __name__=='__main__':main()
