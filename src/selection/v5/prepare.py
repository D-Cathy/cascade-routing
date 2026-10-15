"""CLI: migrate protected development data or plan draft v2 task splits."""
import argparse
import json
from pathlib import Path
from ..routerbench_adapter import validate,digest,write_rows
from ..replay_data import read_jsonl
from .data_contract import validate_tasks,controller_input
from .splits import plan,TARGETS

def run(output,legacy=None,tasks=None,seed=20261014):
    out=Path(output)
    if out.exists():raise FileExistsError('Use a new output directory')
    inputs={}
    if legacy:
        p=Path(legacy);validate(p);old=read_jsonl(p/'tasks.jsonl')
        rows=[dict(schema_version=2,task_id=t['task_id'],source_group_id=t['source_group_id'],
            source_id='routerbench',source_sample_id=t['metadata']['sample_id'],template_family=None,
            category=t['metadata']['eval_name'],question=t['question'],evidence=t['evidence'],
            allowed_models=t['allowed_models'],split='development',provenance='engineering_cache') for t in old]
        inputs={str(p/n):digest(p/n) for n in ['tasks.jsonl','calls.jsonl','labels.jsonl','manifest.json']}
    else:
        rows=read_jsonl(tasks);inputs={str(tasks):digest(tasks)}
    validate_tasks(rows)
    allocated,report=plan(rows,seed=seed)
    out.mkdir(parents=True)
    write_rows(out/'tasks.v2.jsonl',allocated)
    write_rows(out/'controller_inputs.jsonl',[controller_input(t) for t in allocated])
    if legacy:
        (out/'private').mkdir()
        for name in ['calls.jsonl','labels.jsonl']:
            (out/'private'/name).write_bytes((Path(legacy)/name).read_bytes())
    (out/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    manifest={'schema_version':2,'purpose':'draft_data_contract_validation','seed':seed,'input_sha256':inputs,
        'formal_ready':False,'risk_guarantee':False,'targets':TARGETS,
        'development_lock':'All previously used legacy tasks remain development; connected relatives follow locks',
        'private_cache_schema':'legacy_v1_unchanged' if legacy else None,
        'output_sha256':{str(p.relative_to(out)):digest(p) for p in out.rglob('*') if p.is_file()}}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return check(out)

def check(output):
    out=Path(output);m=json.loads((out/'manifest.json').read_text())
    for n,sha in m['output_sha256'].items():
        if digest(out/n)!=sha:raise ValueError('Artifact checksum mismatch')
    rows=read_jsonl(out/'tasks.v2.jsonl');validate_tasks(rows)
    # Re-audit allocated groups to reject cross-split near duplicates.
    from .splits import audit
    audit(rows)
    if read_jsonl(out/'controller_inputs.jsonl')!=[controller_input(t) for t in rows]:raise ValueError('Public input boundary mismatch')
    report=json.loads((out/'audit.json').read_text())
    return {'status':'validated','tasks':len(rows),'actual':report['actual'],'formal_ready':False}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group();g.add_argument('--legacy');g.add_argument('--tasks')
    p.add_argument('--output',required=True);p.add_argument('--seed',type=int,default=20261014);p.add_argument('--validate-only',action='store_true');a=p.parse_args()
    if not a.validate_only and not(a.legacy or a.tasks):p.error('--legacy or --tasks required')
    print(json.dumps(check(a.output) if a.validate_only else run(a.output,a.legacy,a.tasks,a.seed),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
