import json
import pytest
from selection.v5.calibration import upper_bound,freeze,evaluate,verify

def setup(tmp_path):
    artifact=tmp_path/'policy.json';artifact.write_text('{}')
    units=[dict(unit_id=str(i),source_group_id=str(i),split='D_C') for i in range(20)]
    path=tmp_path/'freeze.json';freeze(path,{'a':artifact},units)
    rows=[dict(policy_id='a',unit_id=str(i),split='D_C',service_failure=False) for i in range(20)]
    return path,artifact,rows

def test_zero_failure_closed_form():
    assert upper_bound(0,20)==pytest.approx(1-.05**(1/20))

def test_all_failure_bound():assert upper_bound(20,20)==1

def test_multiple_candidates_conservative():assert upper_bound(2,100,h=11)>upper_bound(2,100,h=1)

def test_small_sample_does_not_pass(tmp_path):
    p,_,rs=setup(tmp_path);r=evaluate(p,rs)
    assert not r['candidates']['a']['passes_reference_bound'] and not r['risk_guarantee']

def test_unknown_blocks_calibration(tmp_path):
    p,_,rs=setup(tmp_path);rs[0]['service_failure']=None
    assert evaluate(p,rs)['candidates']['a']['upper_reference_bound'] is None

def test_missing_rows_rejected(tmp_path):
    p,_,rs=setup(tmp_path)
    with pytest.raises(ValueError):evaluate(p,rs[:-1])

def test_duplicate_units_rejected(tmp_path):
    p,_,rs=setup(tmp_path)
    with pytest.raises(ValueError):evaluate(p,rs+[rs[0]])

def test_test_set_rejected(tmp_path):
    p,_,rs=setup(tmp_path);rs[0]['split']='D_T'
    with pytest.raises(ValueError):evaluate(p,rs)

def test_artifact_change_rejected(tmp_path):
    p,a,_=setup(tmp_path);a.write_text('{"changed":true}')
    with pytest.raises(ValueError):verify(p)

def test_manifest_change_rejected(tmp_path):
    p,_,_=setup(tmp_path);d=json.loads(p.read_text());d['payload']['alpha']=.9;p.write_text(json.dumps(d))
    with pytest.raises(ValueError):verify(p)

def test_group_repetition_rejected(tmp_path):
    a=tmp_path/'a';a.write_text('{}')
    units=[dict(unit_id=str(i),source_group_id='same',split='D_C') for i in range(2)]
    with pytest.raises(ValueError):freeze(tmp_path/'f',{'a':a},units)

def test_unfrozen_candidate_rejected(tmp_path):
    p,_,rs=setup(tmp_path);rs[0]['policy_id']='b'
    with pytest.raises(ValueError):evaluate(p,rs)
