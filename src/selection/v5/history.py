"""Build development transitions with one frozen predicted answer selector."""
from copy import deepcopy
from .gain import ROLES,retained_gain
from .transition_library import public_transition
from ..schema import ModelStatus

def state_features(state,selector):
    values=[selector.estimate(state,m) if m in state.successful_models else 0.0 for m in ROLES]
    values += [float(m in state.attempted_models) for m in ROLES]
    values += [state.remaining_time,state.remaining_budget,state.environment.get('bandwidth_mbps')]
    if any(v is None for v in values):raise ValueError('Unknown state resource; transition unsupported')
    return values

def build_transition(record_id,group,state,call,selector,labels,environment_after):
    if call.model_name not in state.allowed_models or call.model_name in state.attempted_models:raise ValueError('Action unavailable/already attempted')
    if call.latency is None or call.cost is None:raise ValueError('Unknown transition resources')
    before=selector.select_answer(state);after_state=deepcopy(state)
    after_state.attempted_models[call.model_name]=call.status
    if call.status==ModelStatus.SUCCESS:after_state.successful_models[call.model_name]=call.answer
    after=selector.select_answer(after_state)
    row={'record_id':record_id,'source_group_id':group,'action':call.model_name,
         'history':[[m,s.value if hasattr(s,'value') else s] for m,s in state.attempted_models.items()],
         'features':state_features(state,selector),'gains':[0.0]*3,
         'outcome':{'status':call.status.value,'predicted_quality':selector.estimate(after_state,after) if after else 0.0,
                    'latency_s':call.latency,'cost':call.cost,'environment':deepcopy(environment_after)}}
    public_transition(row) # Validates upward legality before producing an offline target.
    row['gain_target']=retained_gain(before,after,labels)
    return row
