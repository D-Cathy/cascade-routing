"""Frozen-family binomial reference bounds. No automatic risk certification."""
import hashlib
import json
import math
from pathlib import Path
from scipy.stats import beta
from ..replay_data import fields
from ..routerbench_adapter import digest

def upper_bound(k,n,delta=.05,h=1):
    if type(n) is not int or type(k) is not int or type(h) is not int or not 0<=k<=n or n<=0 or h<=0:raise ValueError('Invalid counts')
    if not math.isfinite(delta) or not 0<delta<1:raise ValueError('Invalid delta')
    return 1.0 if k==n else float(beta.isf(delta/h,k+1,n-k))

def canonical_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def freeze(path,policies,units,alpha=.1,delta=.05):
    """Record candidate artifacts and planned calibration units BEFORE outcomes."""
    if not policies or not units:raise ValueError('Nonempty candidate family and units required')
    if not 0<alpha<1 or not 0<delta<1:raise ValueError('Invalid alpha/delta')
    for policy_id in policies:
        if not isinstance(policy_id,str) or not policy_id:raise ValueError('Invalid policy ID')
    for u in units:
        fields(u,['unit_id','source_group_id','split'])
        if u['split']!='D_C' or any(not isinstance(u[k],str) or not u[k] for k in ['unit_id','source_group_id']):raise ValueError('Only declared D_C units accepted')
    if len({u['unit_id'] for u in units})!=len(units) or len({u['source_group_id'] for u in units})!=len(units):raise ValueError('One calibration unit per source group required')
    artifacts={name:{'path':str(Path(p).resolve()),'sha256':digest(p)} for name,p in policies.items()}
    payload={'version':1,'policies':artifacts,'units':units,'alpha':alpha,'delta':delta,
             'H':len(policies),'independence_certified':False,'purpose':'reference_bound_only'}
    package={'payload':payload,'payload_sha256':canonical_hash(payload)}
    with Path(path).open('x') as f:json.dump(package,f,indent=2)
    return package

def verify(path):
    package=json.loads(Path(path).read_text());p=package['payload']
    if canonical_hash(p)!=package['payload_sha256']:raise ValueError('Freeze manifest changed')
    if p['H']!=len(p['policies']):raise ValueError('Candidate count mismatch')
    for a in p['policies'].values():
        if digest(a['path'])!=a['sha256']:raise ValueError('Frozen policy artifact changed')
    return p

def evaluate(path,records):
    p=verify(path);ids={u['unit_id'] for u in p['units']};indexed={}
    for r in records:
        fields(r,['policy_id','unit_id','split','service_failure'])
        if r['policy_id'] not in p['policies'] or r['unit_id'] not in ids or r['split']!='D_C':raise ValueError('Unexpected candidate/unit/split')
        if r['service_failure'] is not None and type(r['service_failure']) is not bool:raise ValueError('Failure must be bool or null')
        key=(r['policy_id'],r['unit_id'])
        if key in indexed:raise ValueError('Duplicate result unit')
        indexed[key]=r['service_failure']
    expected={(a,u) for a in p['policies'] for u in ids}
    if set(indexed)!=expected:raise ValueError('Missing result rows; do not drop failed or unknown requests')
    results={}
    for name in p['policies']:
        values=[indexed[(name,u)] for u in ids];k=sum(v is True for v in values);unknown=sum(v is None for v in values)
        bound=upper_bound(k,len(ids),p['delta'],p['H']) if not unknown else None
        results[name]={'n':len(ids),'known_failures':k,'unknown':unknown,'upper_reference_bound':bound,
                       'passes_reference_bound':bound is not None and bound<=p['alpha']}
    return {'candidates':results,'H':p['H'],'alpha':p['alpha'],'delta':p['delta'],
            'risk_guarantee':False,'selected_policy':None,
            'limitations':['source group uniqueness is not verified statistical independence',
                'hashes detect changed artifacts but are not signed proof of pre-outcome freezing',
                'input failures must come from audited full-request evaluation; labels/resources not rederived here',
                'reference pass does not authorize deployment or replace formal applicability review']}
