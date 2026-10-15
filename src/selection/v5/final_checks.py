"""Development acceptance report and 20-unit synthetic calibration demonstration."""
import argparse
import json
from pathlib import Path
from .calibration import freeze,evaluate
from .data_contract import validate_tasks
from ..replay_data import read_jsonl
from ..routerbench_adapter import digest

def run(dataset,output):
    data=Path(dataset);tasks=read_jsonl(data/'tasks.v2.jsonl');validate_tasks(tasks)
    out=Path(output)
    if out.exists():raise FileExistsError('Use a new output directory')
    out.mkdir(parents=True)
    policy=out/'synthetic_policy.json';policy.write_text('{"mode":"synthetic_fixture_only"}\n')
    units=[{'unit_id':f'synthetic-{i}','source_group_id':f'fixture-{i}','split':'D_C'} for i in range(20)]
    freeze(out/'synthetic_freeze.json',{'fixture_policy':policy},units)
    records=[{'policy_id':'fixture_policy','unit_id':u['unit_id'],'split':'D_C','service_failure':False} for u in units]
    bound=evaluate(out/'synthetic_freeze.json',records)
    (out/'synthetic_results.json').write_text(json.dumps(records,indent=2)+'\n')
    (out/'synthetic_calibration.json').write_text(json.dumps(bound,indent=2)+'\n')
    counts={s:sum(t['split']==s for t in tasks) for s in ['development','D_Q','D_G','D_V','D_C','D_T','unassigned']}
    report={'status':'engineering_checks_completed_formal_experiment_not_ready','task_counts':counts,
            'real_model_calls':0,'risk_guarantee':False,'formal_experiment_complete':False,
            'input_sha256':{'tasks.v2.jsonl':digest(data/'tasks.v2.jsonl')},
            'blocking_items':['formal source independence and five-way dataset freeze',
                'paper encoder and service validity labels / trained service classifier',
                'formal donor-to-current-task mapping and calibrated dynamics support',
                'complete paper frontier implementation and strong reference baselines',
                'frozen candidate policies, audited independent calibration and held-out tests',
                'E1–E6 results, ablations and domain validation'],
            'synthetic_demo_note':'20 artificial units, zero failures; not actual D_C data or a real risk claim'}
    (out/'readiness.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False));return report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',required=True);p.add_argument('--output',required=True);a=p.parse_args();run(a.dataset,a.output)
if __name__=='__main__':main()
