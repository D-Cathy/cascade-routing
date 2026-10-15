from copy import deepcopy
import pytest
from selection.v5.data_contract import validate_tasks,controller_input,training_tasks,SPLITS
from selection.v5.splits import audit,plan

def task(i,text=None,**kw):
    t=dict(schema_version=2,task_id=str(i),source_group_id=f'source-{i}',source_id='bench',
        source_sample_id=str(i),template_family=None,category='example',question=text or f'{i}'+chr(65+i)*30,
        evidence='',allowed_models=['ship','shore','cloud'],split='unassigned',provenance='synthetic_test_fixture')
    t.update(kw);return t

def test_strict_label_boundary():
    t=task(0);t['quality']=1
    with pytest.raises(ValueError):validate_tasks([t])

def test_public_whitelist_and_copy():
    t=task(0);p=controller_input(t)
    assert set(p)=={'task_id','source_group_id','question','evidence','allowed_models'}
    p['allowed_models'].clear();assert len(t['allowed_models'])==3

def test_exact_normalization_cross_source():
    a=task(0,'Ａ  TEST');b=task(1,'a test',source_id='other')
    assert len(audit([a,b])['components'])==1

def test_shot_variants_link_by_sample():
    a=task(0,'zero shot');b=task(1,'very different few shot',source_sample_id='0')
    assert len(audit([a,b])['components'])==1

def test_template_transitive_source_union():
    a=task(0,template_family='template');b=task(1,template_family='template')
    c=task(2,source_group_id='source-1')
    assert len(audit([a,b,c])['components'])==1

def test_near_duplicates_grouped():
    s='The vessel reports wind speed and wave height; compare both readings against the supplied limits. '
    a=task(0,s+'A');b=task(1,s+'B')
    assert len(audit([a,b])['components'])==1

def test_existing_cross_partition_duplicates_rejected():
    with pytest.raises(ValueError,match='crosses'):
        audit([task(0,'same text',split='D_Q'),task(1,'same text',split='D_T')])

def test_development_and_relatives_never_recycled():
    rows=[task(0,split='development'),task(1,source_sample_id='0')]
    allocated,r=plan(rows)
    assert all(t['split']=='development' for t in allocated)
    assert r['actual']['D_C']==0 and not r['formal_ready']

def test_six_way_whole_group_deterministic_allocation():
    rows=[task(i) for i in range(6)]
    targets={s:1 for s in SPLITS}
    a,r=plan(rows,targets);b,_=plan(list(reversed(rows)),targets)
    assert r['exact_counts_met'] and set(t['split'] for t in a)==set(SPLITS)
    assert {t['task_id']:t['split'] for t in a}=={t['task_id']:t['split'] for t in b}
    assert not r['formal_ready']

def test_infeasible_counts_reported_not_split_group():
    a,r=plan([task(i,source_group_id='shared') for i in range(6)],{s:1 for s in SPLITS})
    assert len({t['split'] for t in a})==1 and not r['exact_counts_met']

def test_training_stage_excludes_calibration_and_test():
    rows=[task(i,split=s) for i,s in enumerate(SPLITS)]
    assert [t['split'] for t in training_tasks(rows,'score')]==['D_Q']
    with pytest.raises(ValueError):training_tasks(rows,'D_T')

def test_unknown_fields_and_duplicate_id():
    with pytest.raises(ValueError):validate_tasks([task(0),task(0)])
    with pytest.raises(ValueError):validate_tasks([task(0,split='test')])
