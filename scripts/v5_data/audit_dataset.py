"""Audit the candidate corpus and existing v1 development boundary, offline."""
import collections
import hashlib
import json
import pathlib
import sys

ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
from selection.replay_data import validate_tasks
DATA=ROOT/'data/v5_public_20261013'
P=DATA/'prepared'
def read(name):return [json.loads(s) for s in (P/name).read_text().splitlines()]

def main():
    tasks=read('tasks.jsonl');refs=read('private/references.jsonl');labels=read('private/labels.pending.jsonl');dev=read('dev20.tasks.v1.jsonl')
    checks=[]
    def check(name,condition):
        if not condition:raise AssertionError(name)
        checks.append(name)
    ids={t['task_id'] for t in tasks}
    check('1600 unique tasks / five balanced categories',len(tasks)==len(ids)==1600 and set(collections.Counter(t['category'] for t in tasks).values())=={320})
    check('reference one-to-one alignment',len(refs)==len(ids) and {r['task_id'] for r in refs}==ids)
    check('4800 unique missing labels',len(labels)==4800 and len({(r['task_id'],r['model_name']) for r in labels})==4800 and all(r['task_id'] in ids and r['quality'] is None and r['valid'] is None and r['label_source']=='missing' for r in labels))
    check('no formal split or verified-human claim',all(t['split'] in {'unassigned','development_reserved'} and t['human_review_status']=='pending' for t in tasks) and all(not r['human_verified'] for r in refs))
    check('public task boundary excludes evaluation fields',all(not {'reference','quality','valid','answer','cost','latency_s'} & t.keys() for t in tasks))
    groups=collections.defaultdict(set)
    for t in tasks:groups[t['source_group_id']].add(t['split'])
    check('source groups never cross reserved/unassigned boundary',all(len(s)==1 for s in groups.values()))
    validate_tasks(dev,['ship','shore','cloud'])
    check('20 tasks accepted by existing strict v1 validator',len(dev)==20)
    rg={t['source_group_id'] for t in dev}
    check('all relatives of development examples reserved',all(t['split']=='development_reserved' for t in tasks if t['source_group_id'] in rg))
    references={r['task_id']:r['reference'] for r in refs}
    for t in tasks:
        e=json.loads(t['evidence']);r=references[t['task_id']];c=t['category']
        if c=='log_summary':
            assert abs(r['mean_speed_raw']-sum(float(x['Speed']) for x in e['records'])/6)<=0.00501
        elif c=='weather':
            w=[x['WSPD'] for x in e['records'] if x['WSPD'] is not None]
            assert r['max_wind_m_s']==max(w) and all(x['WVHT']!=99 for x in e['records'])
            assert r['missing_cells']==sum(x[k] is None for x in e['records'] for k in ['WSPD','WVHT','PRES'])
        elif c=='equipment':
            flags=[k for k in ['compressor','turbine'] if e[k+'_coefficient']<e['rule'][k+'_threshold']]
            assert flags==r['flagged_components']
        elif c=='alternatives':
            feasible=[x for x in e['options'] if x['speed_knots']>=e['minimum_speed_knots'] and x['fuel_kg_s']<=e['max_fuel_kg_s']]
            assert r['feasible_ids']==[x['id'] for x in feasible]
            assert r['selected_id']==(sorted(feasible,key=lambda x:(x['fuel_kg_s'],x['id']))[0]['id'] if feasible else None)
        else:
            us=e['utterances']
            if 'turn_counts' in r:assert r['turn_counts']==dict(collections.Counter(str(u['speaker_id']) for u in us))
            else:assert r['question_turns']==[u['turn'] for u in us if '?' in u['text']]
    check('1600 references checked against evidence computations',True)
    hashes=json.loads((DATA/'file_hashes.json').read_text())
    check('saved file SHA256 matches',all(hashlib.sha256((DATA/n).read_bytes()).hexdigest()==h for n,h in hashes.items()))
    meta=json.loads((DATA/'raw/polarfront_metadata.json').read_text())
    verified=0
    for f in meta['files']:
        path=DATA/'raw/polarfront'/f['key']
        if path.exists():
            assert path.stat().st_size==f['size']
            if f.get('checksum','').startswith('md5:'):assert hashlib.md5(path.read_bytes()).hexdigest()==f['checksum'].split(':')[1]
            verified+=1
    check('downloaded PolarFront files match upstream size/checksum',verified>0)
    result={'status':'passed','checks_passed':len(checks),'checks':checks,'tasks_audited':len(tasks),'dev_tasks_validated':len(dev),'polarfront_files_verified':verified,'model_calls':0,'human_review_completed':False}
    report=ROOT/'reports/v5_dataset_20261013_01/validation.json'
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
