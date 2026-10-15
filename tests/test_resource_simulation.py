import copy
import json
from pathlib import Path
import pytest
from selection.resource_simulation import LinkTimeline, SimulatedCachedModel
from selection.executor import UnifiedExecutor
from selection.policies import FixedOrderPolicy
from selection.schema import ModelStatus

CFG=json.loads((Path(__file__).parents[1]/'configs/routerbench_simulation.json').read_text())

def model(role='shore',segments=None,cfg=None,answer='a'*100):
    cfg=copy.deepcopy(cfg or CFG)
    link=LinkTimeline('test',segments or cfg['regimes']['normal'])
    cached={'model_version':'original-model','answer':answer,'cost':1234}
    return SimulatedCachedModel(role,cached,'task-1',cfg,link)

def segment(t,b):return {'at_s':t,'bandwidth_mbps':b,'one_way_latency_s':0}

def test_piecewise_bandwidth_integration():
    link=LinkTimeline('test',[segment(0,1),segment(1,0.5)])
    end,moved,error=link.transfer(0,187500,10)
    assert end==2 and moved==187500 and error is None

def test_outage_retains_partial_bytes():
    link=LinkTimeline('test',[segment(0,1),segment(1,0),segment(3,1)])
    end,moved,error=link.transfer(0,200000,10)
    assert end==1 and moved==125000 and error=='link_interrupted'
    assert link.transfer(3,125000,10)==(4,125000,None)

def test_transfer_timeout():
    link=LinkTimeline('test',[segment(0,1)])
    end,moved,error=link.transfer(0,250000,1)
    assert (end,moved,error)==(1,125000,'call_timeout')

def test_failure_detection_and_cancellation():
    m=model(segments=[segment(0,0)])
    call=m.call_at('question','evidence',0)
    assert call.status==ModelStatus.FAILED and call.answer is None
    assert call.latency==pytest.approx(.6) and call.cost==0
    assert call.metadata['components']['detection_s']==.5

def test_local_unaffected_by_network():
    a=model('ship',segments=[segment(0,0)]).call_at('q','e',0)
    b=model('ship').call_at('q','e',0)
    assert a.status==ModelStatus.SUCCESS and a.latency==b.latency and a.cost==b.cost
    assert a.metadata['transferred_bytes']==0

def test_downlink_failure_keeps_compute_charge():
    cfg=copy.deepcopy(CFG);cfg['models']['shore']['base_compute_s']=2
    m=model(cfg=cfg,segments=[segment(0,1),segment(1,0)])
    c=m.call_at('q','e',0)
    assert c.status==ModelStatus.FAILED and c.answer is None and c.cost>0
    assert c.metadata['simulated_compute_fee']>0 and c.metadata['transferred_bytes']==4

def test_timeout_partial_compute_and_no_raw_cost_charge():
    cfg=copy.deepcopy(CFG);cfg['call_timeout_s']=.2;cfg['models']['ship']['queue_max_s']=0
    c=model('ship',cfg=cfg).call_at('q','e',0)
    assert c.reason=='call_timeout' and c.latency==pytest.approx(.3)
    assert c.metadata['components']['compute_s']==.2
    assert c.cost==pytest.approx(.5*.2*.04)
    assert c.metadata['original_cache_cost']==1234

def test_resource_conservation():
    c=model().call_at('q','e',4)
    assert c.latency==pytest.approx(sum(c.metadata['components'].values()))
    assert c.cost==pytest.approx(c.metadata['normalized_fee_cost']+c.metadata['normalized_transfer_cost'])
    assert c.latency_source==c.cost_source=='simulated' and c.quality is None

def test_executor_dynamic_clock_no_retry_and_public_state():
    cfg=copy.deepcopy(CFG);cfg['models']['ship']['base_compute_s']=2
    link=LinkTimeline('test',[segment(0,1),segment(1,0),segment(8,1)])
    models=[model(n,cfg=cfg,segments=link.segments) for n in ['ship','shore','cloud']]
    policy=FixedOrderPolicy(['ship','shore','cloud'])
    trace=UnifiedExecutor(models,12,100,.8,policy=policy,decision_overhead=.01,environment_observer=link.observe).execute({'question':'q','evidence':'e'})
    assert [c.model_name for c in trace.model_calls]==['ship','shore','cloud']
    assert trace.model_calls[1].status==ModelStatus.FAILED
    assert trace.events[1]['state']['environment']['bandwidth_mbps']==0
    assert set(trace.events[0]['state']['environment'])=={'network_regime','bandwidth_mbps','observed_at_s'}
    assert trace.model_calls[1].metadata['start_s']==pytest.approx(trace.model_calls[0].latency+.02)
    assert trace.total_time==pytest.approx(sum(c.latency for c in trace.model_calls)+.01*len(trace.decisions))

def test_shared_seed_and_original_input_only():
    m=model();a=m.call_at('original question','fixed evidence',0)
    b=model().call_at('original question','fixed evidence',0)
    assert a==b
    assert a.metadata['transferred_bytes']==len('original question\n\nfixed evidence'.encode())+100

def test_simulator_not_accepted_as_live_backend():
    with pytest.raises(ValueError):
        UnifiedExecutor([model()],12,1,.8,execution_timing='wall_clock',decision_timing='measured',environment_observer=lambda t:{})
