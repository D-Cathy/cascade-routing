"""Finite three-role development planner over explicit observable-state scenarios.

Enumerates consistent continuation policies; Pareto filtering at root only.
Transition providers must supply predictions, never reference labels or donor IDs.
"""
from dataclasses import dataclass
from itertools import product
import math
import time

ROLES=('ship','shore','cloud')

@dataclass(frozen=True)
class PlanningState:
    history: tuple = ()
    remaining_time: float = 12.0
    remaining_cost: float = 1.5
    quality: float = 0.0
    pass_probability: float | None = None
    has_answer: bool = False
    allowed: tuple = ROLES
    bandwidth: float = 1.0

    def __post_init__(self):
        ranks=[]
        for role,status in self.history:
            if role not in ROLES or status not in ('SUCCESS','FAILED','INVALID'):raise ValueError('Invalid history')
            ranks.append(ROLES.index(role))
        if ranks!=sorted(set(ranks)):raise ValueError('History must be strictly upward')
        if len(set(self.allowed))!=len(self.allowed) or any(m not in ROLES for m in self.allowed):raise ValueError('Invalid permissions')
        for x in (self.remaining_time,self.remaining_cost,self.quality,self.bandwidth):
            if not math.isfinite(x) or x<0:raise ValueError('Invalid state value')
        if self.quality>1 or (self.pass_probability is not None and (not math.isfinite(self.pass_probability) or not 0<=self.pass_probability<=1)):raise ValueError('Invalid prediction')

    def key(self):
        # No source/donor IDs. Exact resources, not rounded bins, define state.
        return repr((self.history,float(self.remaining_time).hex(),float(self.remaining_cost).hex(),
            float(self.quality).hex(),None if self.pass_probability is None else float(self.pass_probability).hex(),
            self.has_answer,self.allowed,float(self.bandwidth).hex()))

@dataclass(frozen=True)
class Scenario:
    weight: float
    state: PlanningState
    latency: float
    cost: float

@dataclass
class Candidate:
    vector: tuple
    action: str
    continuation: dict

def pareto(candidates):
    result=[]
    for c in sorted(candidates,key=lambda c:(c.vector,c.action,repr(sorted(c.continuation.items())))):
        if any(all(a<=b for a,b in zip(p.vector,c.vector)) for p in result):continue
        result=[p for p in result if not all(a<=b for a,b in zip(c.vector,p.vector))]
        result.append(c)
    return result

class FinitePlanner:
    def __init__(self,provider,deadline=12.,budget=1.5,quality_gate=.8,rho=.1,
                 lambda_time=.1,lambda_cost=.1,timeout_s=.05,epsilon=None,max_front=32):
        for v in (deadline,budget,timeout_s):
            if not math.isfinite(v) or v<=0:raise ValueError('Positive scale/timeout required')
        for v in (quality_gate,rho):
            if not math.isfinite(v) or not 0<=v<=1:raise ValueError('Invalid gate')
        for v in (lambda_time,lambda_cost):
            if not math.isfinite(v) or v<0:raise ValueError('Invalid objective weight')
        if epsilon is not None and (not math.isfinite(epsilon) or epsilon<=0):raise ValueError('Invalid grid')
        if type(max_front) is not int or max_front<1:raise ValueError('Invalid frontier cap')
        self.provider=provider;self.deadline=deadline;self.budget=budget;self.gate=quality_gate;self.rho=rho
        self.lt=lambda_time;self.lc=lambda_cost;self.timeout=timeout_s;self.epsilon=epsilon;self.cap=max_front

    def acceptable(self,s):return s.has_answer and s.quality>=self.gate and s.pass_probability is not None
    def rank(self,c):
        q,t,b,f=c.vector
        return (f>self.rho,q+self.lt*t/self.deadline+self.lc*b/self.budget,b,t,c.action,repr(sorted(c.continuation.items())))

    def plan(self,state):
        end=time.perf_counter()+self.timeout;memo={};unsupported=[]
        def guard():
            if time.perf_counter()>end:raise TimeoutError('planning_timeout')
        def visit(s):
            guard();key=s.key()
            if key in memo:return memo[key]
            candidates=[Candidate((1.,0.,0.,1.),'FAIL',{key:'FAIL'})]
            if self.acceptable(s):candidates.append(Candidate((1-s.quality,0.,0.,1-s.pass_probability),'ACCEPT',{key:'ACCEPT'}))
            rank=ROLES.index(s.history[-1][0]) if s.history else -1
            for role in s.allowed:
                if ROLES.index(role)<=rank:continue
                guard();scenarios=self.provider(s,role);guard()
                if not scenarios:
                    unsupported.append((key,role));continue
                total=sum(x.weight for x in scenarios)
                if not math.isfinite(total) or abs(total-1)>1e-9:raise ValueError('Scenario weights must sum to one')
                feasible=True
                for x in scenarios:
                    if not all(math.isfinite(v) and v>=0 for v in (x.weight,x.latency,x.cost)):raise ValueError('Invalid scenario resource/weight')
                    if x.state.history[:-1]!=s.history or len(x.state.history)!=len(s.history)+1 or x.state.history[-1][0]!=role:raise ValueError('Transition must append exactly selected action')
                    if x.latency>s.remaining_time or x.cost>s.remaining_cost:feasible=False;continue
                    if abs(x.state.remaining_time-(s.remaining_time-x.latency))>1e-9 or abs(x.state.remaining_cost-(s.remaining_cost-x.cost))>1e-9:raise ValueError('Child ledger mismatch')
                    if not set(x.state.allowed)<=set(s.allowed):raise ValueError('Transition cannot grant new permissions')
                if not feasible:continue
                # Aggregate identical observations BEFORE selecting continuation.
                grouped={}
                for x in scenarios:
                    if x.weight==0:continue
                    k=x.state.key()
                    if k not in grouped:grouped[k]=[x.state,0.,0.,0.]
                    g=grouped[k];g[1]+=x.weight;g[2]+=x.weight*x.latency;g[3]+=x.weight*x.cost
                branches=[(g,visit(g[0])) for k,g in sorted(grouped.items())]
                for choices in product(*(cs for g,cs in branches)):
                    guard();mapping={key:'CALL:'+role};vector=[0.,0.,0.,0.];consistent=True
                    for (g,_),c in zip(branches,choices):
                        for k,a in c.continuation.items():
                            if k in mapping and mapping[k]!=a:consistent=False;break
                            mapping[k]=a
                        for i,v in enumerate(c.vector):vector[i]+=g[1]*v
                        vector[1]+=g[2];vector[2]+=g[3]
                    if consistent:candidates.append(Candidate(tuple(vector),'CALL:'+role,mapping))
            memo[key]=candidates;return candidates
        try:
            all_candidates=visit(state);guard();front=pareto(all_candidates);guard();uncompressed=len(front)
            if self.epsilon is not None:
                bins={}
                for c in sorted(front,key=self.rank):
                    v=c.vector;cell=tuple(math.floor(x/self.epsilon) for x in (v[0],v[1]/self.deadline,v[2]/self.budget,v[3]))
                    bins.setdefault(cell,c)
                front=sorted(bins.values(),key=self.rank)[:self.cap]
            feasible=[c for c in front if c.vector[3]<=self.rho]
            if feasible:
                best=min(feasible,key=self.rank)
                return {'action':best.action,'vector':best.vector,'continuation':best.continuation,
                    'reason':'predicted_frontier','frontier_size':len(front),'uncompressed_size':uncompressed,
                    'unsupported_actions':len(unsupported),'risk_guarantee':False}
            reason='no_risk_feasible_candidate'
        except TimeoutError:reason='planning_timeout'
        return {'action':'ACCEPT' if self.acceptable(state) else 'FAIL','vector':None,
                'continuation':{},'reason':reason,'unsupported_actions':len(unsupported),'risk_guarantee':False}
