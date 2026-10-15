import csv
import json
import pytest
from selection.routerbench_adapter import MODELS, convert, validate, text_cell, numeric

def fixture_csv(tmp_path, mutate=None):
    rows=[]
    for i in range(20):
        r={'sample_id':str(i),'prompt':repr(['Instruction',f'Question {i}']), 'eval_name':f'family{i%4}'}
        for m in MODELS.values():
            r.update({m:'0',m+'|model_response':repr(['cached answer']),m+'|total_cost':'0.001'})
        rows.append(r)
    if mutate:mutate(rows)
    path=tmp_path/'input.csv'
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
    return path

def read(out,name):return [json.loads(s) for s in (out/name).read_text().splitlines()]

def test_export_boundaries_and_all_wrong_retained(tmp_path):
    out=tmp_path/'out';result=convert(fixture_csv(tmp_path),out)
    assert result['tasks']==20 and result['calls']==60 and result['labels']==60
    tasks=read(out,'tasks.jsonl');calls=read(out,'calls.jsonl');labels=read(out,'labels.jsonl')
    assert all('quality' not in t and 'answer' not in t and 'oracle_model_to_route_to' not in t for t in tasks)
    assert all(c['latency_s'] is None and c['cost']==.001 and 'quality' not in c for c in calls)
    assert all(l['quality']==0 and l['valid'] is None for l in labels)
    groups={}
    for t in tasks:groups.setdefault(t['source_group_id'],set()).add(t['split'])
    assert all(len(s)==1 for s in groups.values())
    assert {t['split'] for t in tasks}=={'dev_fit','dev_eval'}

def test_reproducible_and_no_overwrite(tmp_path):
    src=fixture_csv(tmp_path);a=tmp_path/'a';b=tmp_path/'b'
    convert(src,a);convert(src,b)
    for n in ['tasks.jsonl','calls.jsonl','labels.jsonl']:assert (a/n).read_bytes()==(b/n).read_bytes()
    with pytest.raises(FileExistsError):convert(src,a)

def test_missing_values_not_zero(tmp_path):
    m=next(iter(MODELS.values()))
    def mutate(rows):rows[0].update({m:'',m+'|total_cost':'',m+'|model_response':''})
    out=tmp_path/'out';convert(fixture_csv(tmp_path,mutate),out)
    c=next(c for c in read(out,'calls.jsonl') if c['task_id'].endswith(':0') and c['model_name']=='ship')
    assert c['cost'] is None and c['cost_source']=='missing' and c['status']=='INVALID'
    l=next(l for l in read(out,'labels.jsonl') if l['task_id'].endswith(':0') and l['model_name']=='ship')
    assert l['quality'] is None and l['label_source']=='missing'

def test_duplicate_id_rejected(tmp_path):
    def mutate(rows):rows[1]['sample_id']=rows[0]['sample_id']
    with pytest.raises(ValueError,match='duplicate'):convert(fixture_csv(tmp_path,mutate),tmp_path/'out')

def test_cross_family_duplicate_prompt_rejected(tmp_path):
    def mutate(rows):rows[1]['prompt']=rows[0]['prompt']
    with pytest.raises(ValueError,match='Duplicate prompt'):convert(fixture_csv(tmp_path,mutate),tmp_path/'out')

@pytest.mark.parametrize('value',['nan','inf','-1','1.1'])
def test_bad_quality_rejected(value):
    with pytest.raises(ValueError):numeric(value,1)

def test_text_parsing_no_execution():
    assert text_cell("['a', 'b']")=='a\n\nb'
    with pytest.raises(ValueError):text_cell("[__import__('os').system('false')]")

def test_checksum_tampering_rejected(tmp_path):
    out=tmp_path/'out';convert(fixture_csv(tmp_path),out)
    with (out/'tasks.jsonl').open('a') as f:f.write('\n')
    with pytest.raises(ValueError,match='checksum'):validate(out)
