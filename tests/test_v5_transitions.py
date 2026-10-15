from copy import deepcopy
import pytest
from selection.v5.gain import retained_gain,GainModels
from selection.v5.transition_library import JointTransitionLibrary,public_transition
from selection.v5.history import build_transition
from selection.v5.selector import PredictedThresholdProxy
from selection.v5.demo_transition import FixtureScorer
from selection.schema import ObservableState,ModelCallRecord,ModelStatus

def row(i):
    return dict(record_id=str(i),source_group_id=f'g{i}',action='shore',history=[['ship','SUCCESS']],
        features=[i/10,1],gains=[0,-.2,0],outcome={'status':'SUCCESS','predicted_quality':i/10,'latency_s':i+1.,'cost':(i+1)/10,'environment':{'bandwidth_mbps':1.}})

def query():return {k:row(0)[k] for k in ['action','history','features','gains']}

def test_signed_retained_gain_not_oracle():
    assert retained_gain('ship','shore',{'ship':.9,'shore':.2,'cloud':1})==pytest.approx(-.7)
    assert retained_gain(None,'ship',{'ship':.9})==.9

def test_missing_reference_rejected():
    with pytest.raises(ValueError):retained_gain('ship','shore',{'ship':.9})

def test_public_export_strips_targets():
    r=row(0);r['gain_target']=-.5;r['reference_quality']=1
    assert 'gain_target' not in public_transition(r) and 'reference_quality' not in public_transition(r)
    with pytest.raises(ValueError):JointTransitionLibrary([r])

def test_nested_hidden_label_rejected():
    r=row(0);r['outcome']['quality']=1
    with pytest.raises(ValueError):JointTransitionLibrary([r])

def test_group_uniqueness_and_insufficient_support():
    rows=[row(i) for i in range(6)];rows[1]['source_group_id']='g0'
    lib=JointTransitionLibrary(rows,min_groups=5)
    ns=lib.neighbors(query())['neighbors']
    assert len(ns)==5 and len({n['record']['source_group_id'] for n in ns})==5
    assert not lib.neighbors(query(),exclude_group='g0')['supported']

def test_exact_history_filter():
    lib=JointTransitionLibrary([row(i) for i in range(6)])
    q=query();q['history']=[['ship','FAILED']]
    assert not lib.neighbors(q)['supported']

def test_distance_rejection():
    lib=JointTransitionLibrary([row(i) for i in range(6)],max_distance=.1)
    q=query();q['features']=[100,1]
    assert lib.neighbors(q)['reason']=='out_of_support'

def test_joint_sampling_correlation_and_weights():
    lib=JointTransitionLibrary([row(i) for i in range(6)])
    a=lib.sample(query(),'id');b=lib.sample(query(),'id')
    assert a==b and sum(s['weight'] for s in a['scenarios'])==1
    for s in a['scenarios']:
        assert s['outcome']['cost']==pytest.approx(s['outcome']['latency_s']/10)
        assert s['weight']*4==int(s['weight']*4)

def test_gain_mask_negative_and_frozen():
    rows=[dict(row(i),gain_target=-.5) for i in range(6)]
    m=GainModels().fit(rows);p=m.predict([.1,1],['shore'])
    assert p['gain_vector'][1]<0 and p['gain_vector'][0]==0 and p['action_mask']==[False,True,False]
    with pytest.raises(ValueError):m.fit(rows)

def test_illegal_downward_transition_rejected():
    r=row(0);r['action']='ship'
    with pytest.raises(ValueError):JointTransitionLibrary([r])

def test_builder_uses_predicted_selector_and_labels_only_for_target():
    s=ObservableState('q','e',['shore'],attempted_models={'ship':ModelStatus.SUCCESS},successful_models={'ship':'.4'},remaining_time=10,remaining_budget=2,environment={'bandwidth_mbps':1})
    c=ModelCallRecord('shore','shore',ModelStatus.SUCCESS,1,.1,answer='.7')
    selector=PredictedThresholdProxy(FixtureScorer())
    a=build_transition('id','g',s,c,selector,{'ship':1,'shore':0},{'bandwidth_mbps':.2})
    b=build_transition('id','g',s,c,selector,{'ship':0,'shore':1},{'bandwidth_mbps':.2})
    assert a['gain_target']==-1 and b['gain_target']==1
    assert public_transition(a)==public_transition(b)
    assert list(s.successful_models)==['ship']

def test_unknown_resources_not_zero():
    r=row(0);r['outcome']['latency_s']=None
    with pytest.raises(ValueError):JointTransitionLibrary([r])
