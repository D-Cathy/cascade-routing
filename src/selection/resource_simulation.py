"""Time-indexed, deterministic serial resource simulator. No network or sleep."""
import hashlib
from bisect import bisect_right
from .schema import ModelCallRecord, ModelLevel, ModelStatus

class LinkTimeline:
    def __init__(self, name, segments):
        self.name, self.segments = name, segments
        self.times = [s['at_s'] for s in segments]

    def at(self, now):
        return self.segments[bisect_right(self.times, now)-1]

    def observe(self, now):
        return {'network_regime':self.name,'bandwidth_mbps':self.at(now)['bandwidth_mbps'],
                'observed_at_s':now}

    def transfer(self, now, size, end):
        """Integrate bandwidth across boundaries; zero bandwidth fails, no retry."""
        moved=0.0
        while moved < size:
            if now >= end: return now,moved,'call_timeout'
            i=bisect_right(self.times,now)-1
            rate=self.segments[i]['bandwidth_mbps']*1e6/8
            if rate==0:return now,moved,'link_interrupted'
            boundary=self.times[i+1] if i+1<len(self.times) else end
            stop=min(boundary,end,now+(size-moved)/rate)
            delta=stop-now
            moved=min(float(size),moved+delta*rate)
            now=stop
            if size-moved < 1e-7:moved=float(size)
        return now,moved,None

class SimulatedCachedModel:
    available=True
    def __init__(self, role, cached, task_id, config, timeline):
        self.name=role;self.level=ModelLevel(role);self.cached=cached
        self.model_version=cached['model_version'];self.data_source='engineering_cache'
        self.cfg=config;self.link=timeline
        h=hashlib.sha256(f'{config["seed"]}:{task_id}:{role}:queue'.encode()).digest()
        self.queue_fraction=int.from_bytes(h[:8],'big')/2**64

    def call_at(self, question, evidence, start_s):
        cfg=self.cfg;spec=cfg['models'][self.name]
        now=start_s;end=start_s+cfg['call_timeout_s']
        components={k:0.0 for k in ['upload_s','queue_s','compute_s','download_s','detection_s','cancellation_s']}
        byte_count=0.0;failure=None
        answer=self.cached['answer']
        request_bytes=len((question+'\n\n'+evidence).encode('utf-8'))
        answer_bytes=len((answer or '').encode('utf-8'))
        compute=spec['base_compute_s']+answer_bytes*spec['seconds_per_output_byte']

        def delay(duration,key):
            nonlocal now,failure
            actual=min(duration,max(0.0,end-now));now+=actual;components[key]+=actual
            if actual < duration:failure='call_timeout'

        def transfer(size,key):
            nonlocal now,byte_count,failure
            if self.link.at(now)['bandwidth_mbps']==0:
                failure='link_interrupted';return
            # Propagation delay sampled at phase start. Transfer bandwidth integrated.
            delay(self.link.at(now)['one_way_latency_s'],key)
            if failure:return
            before=now;now,moved,failure=self.link.transfer(now,size,end)
            byte_count+=moved;components[key]+=now-before

        remote=self.name!='ship'
        if remote:transfer(request_bytes,'upload_s')
        if not failure:delay(spec['queue_max_s']*self.queue_fraction,'queue_s')
        if not failure:delay(compute,'compute_s')
        if not failure and remote:transfer(answer_bytes,'download_s')
        if failure:
            # Detection respects call timeout; cancellation is separately charged.
            if failure=='link_interrupted':
                actual=min(cfg['failure_detection_s'],max(0,end-now))
                now+=actual;components['detection_s']=actual
            components['cancellation_s']=cfg['cancellation_s'];now+=cfg['cancellation_s']
        fee=components['compute_s']*spec['fee_per_compute_s']
        fee_part=cfg['fee_weight']*fee/cfg['fee_reference']
        byte_part=(1-cfg['fee_weight'])*byte_count/cfg['byte_reference']
        status=ModelStatus.FAILED if failure else (ModelStatus.SUCCESS if answer and answer.strip() else ModelStatus.INVALID)
        return ModelCallRecord(self.name,self.level.value,status,now-start_s,fee_part+byte_part,
            answer=None if failure else answer,quality=None,reason=failure or 'cached_text_simulated_resources',
            model_version=self.model_version,data_source='engineering_cache',latency_source='simulated',cost_source='simulated',
            metadata={'start_s':start_s,'finish_s':now,'components':components,'transferred_bytes':byte_count,
                      'simulated_compute_fee':fee,'normalized_fee_cost':fee_part,'normalized_transfer_cost':byte_part,
                      'original_cache_cost':self.cached['cost'],'original_cache_cost_used_in_charge':False,
                      'cost_unit':'simulated_normalized_fee_and_bytes','upstream_quality_not_read':True})
