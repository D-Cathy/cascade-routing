"""Label-free joint donor retrieval with group support and deterministic sampling."""
from copy import deepcopy
import hashlib
import json
import numpy as np
from ..replay_data import fields,number
from .gain import ROLES

PUBLIC=('record_id','source_group_id','action','history','features','gains','outcome')

def public_transition(row):
    out=deepcopy({k:row[k] for k in PUBLIC})
    validate_record(out)
    return out

def validate_record(r):
    fields(r,PUBLIC)
    if r['action'] not in ROLES:raise ValueError('Unknown action')
    for k in ['record_id','source_group_id']:
        if not isinstance(r[k],str) or not r[k]:raise ValueError('Missing record/group ID')
    for key in ['features','gains']:
        if not isinstance(r[key],list) or not r[key] or any(type(v) not in (int,float) or not np.isfinite(v) for v in r[key]):raise ValueError('Invalid numeric vector')
    if len(r['gains'])!=3:raise ValueError('Three action gains required')
    history=r['history']
    if not isinstance(history,list):raise ValueError('Invalid history')
    ranks=[]
    for h in history:
        if not isinstance(h,list) or len(h)!=2 or h[0] not in ROLES or h[1] not in ['SUCCESS','FAILED','INVALID']:raise ValueError('Invalid history item')
        ranks.append(ROLES.index(h[0]))
    if ranks!=sorted(set(ranks)) or (ranks and ROLES.index(r['action'])<=ranks[-1]):raise ValueError('Illegal upward action')
    o=r['outcome'];fields(o,['status','predicted_quality','latency_s','cost','environment'])
    if o['status'] not in ['SUCCESS','FAILED','INVALID']:raise ValueError('Invalid outcome')
    number(o['predicted_quality'],'predicted_quality',maximum=1)
    for k in ['latency_s','cost']:number(o[k],k)
    fields(o['environment'],['bandwidth_mbps'])
    number(o['environment']['bandwidth_mbps'],'bandwidth')

class JointTransitionLibrary:
    def __init__(self,rows,kappa=1.0,min_groups=5,max_groups=20,max_distance=3.0):
        if not rows:raise ValueError('Empty library')
        if type(min_groups) is not int or type(max_groups) is not int or not 1<=min_groups<=max_groups:raise ValueError('Invalid group limits')
        number(kappa,'kappa');number(max_distance,'max_distance')
        for r in rows:validate_record(r)
        if len({r['record_id'] for r in rows})!=len(rows):raise ValueError('Duplicate record ID')
        self.rows=deepcopy(rows);self.kappa=kappa;self.min_groups=min_groups;self.max_groups=max_groups;self.max_distance=max_distance
        self.dimension=len(rows[0]['features'])
        if any(len(r['features'])!=self.dimension for r in rows):raise ValueError('Feature dimension mismatch')
        base=np.asarray([r['features'] for r in rows]);g=np.asarray([r['gains'] for r in rows])
        self.base_scale=np.maximum(np.std(base,axis=0),1e-6);self.gain_scale=np.maximum(np.std(g,axis=0),1e-6)

    def neighbors(self,query,exclude_group=None):
        fields(query,['action','history','features','gains'])
        probe=dict(record_id='query',source_group_id='query',outcome={'status':'SUCCESS','predicted_quality':0,'latency_s':0,'cost':0,'environment':{'bandwidth_mbps':0}},**query)
        validate_record(probe)
        if len(query['features'])!=self.dimension:raise ValueError('Feature dimension mismatch')
        candidates=[]
        for r in self.rows:
            if r['action']!=query['action'] or r['history']!=query['history'] or r['source_group_id']==exclude_group:continue
            x=(np.array(r['features'])-query['features'])/self.base_scale
            g=(np.array(r['gains'])-query['gains'])/self.gain_scale
            distance=float(np.linalg.norm(np.r_[x,self.kappa*g]))
            candidates.append((distance,r['record_id'],r))
        unique=[];seen=set()
        for dist,rid,r in sorted(candidates,key=lambda x:(x[0],x[1])):
            if r['source_group_id'] in seen:continue
            seen.add(r['source_group_id']);unique.append((dist,r))
            if len(unique)==self.max_groups:break
        if len(unique)<self.min_groups:return {'supported':False,'reason':'insufficient_source_groups','neighbors':[]}
        if unique[0][0]>self.max_distance:return {'supported':False,'reason':'out_of_support','neighbors':[]}
        distances=np.array([d for d,r in unique]);width=max(float(np.median(distances)),1e-6)
        # Engineering Gaussian kernel; not claimed as a verified reproduction of Eq 3.12.
        logw=-.5*(distances/width)**2;weights=np.exp(logw-logw.max());weights/=weights.sum()
        return {'supported':True,'reason':None,'neighbors':[{'distance':d,'weight':float(w),'record':deepcopy(r)} for (d,r),w in zip(unique,weights)]}

    def sample(self,query,request_id,seed=20261014,draws=4,exclude_group=None):
        if type(draws) is not int or draws<=0:raise ValueError('Positive integer draws required')
        result=self.neighbors(query,exclude_group)
        if not result['supported']:return {**result,'scenarios':[]}
        key=json.dumps([request_id,query,seed,'joint-proxy-v1'],sort_keys=True,separators=(',',':'),allow_nan=False)
        rng=np.random.Generator(np.random.PCG64(int.from_bytes(hashlib.sha256(key.encode()).digest()[:8],'big')))
        ns=result['neighbors'];indices=rng.choice(len(ns),size=draws,p=[n['weight'] for n in ns])
        counts=np.bincount(indices,minlength=len(ns))
        result['scenarios']=[{'weight':int(n)/draws,'donor_record_id':ns[i]['record']['record_id'],
            'outcome':deepcopy(ns[i]['record']['outcome'])} for i,n in enumerate(counts) if n]
        return result
