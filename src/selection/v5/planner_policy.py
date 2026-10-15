"""Receding-horizon adapter. No labels, caches, or donor answers enter policy."""
from .selector import PredictedThresholdProxy
from .planner import PlanningState,FinitePlanner
from ..schema import ActionDecision,ActionType

class PlannerPolicy(PredictedThresholdProxy):
    def __init__(self,scorer,provider_factory,**planner_options):
        super().__init__(scorer)
        self.provider_factory=provider_factory;self.options=planner_options;self.plans=[]

    def decide(self,state):
        if state.remaining_time is None or state.remaining_budget is None:
            return ActionDecision(ActionType.FAIL,reason='unknown_resources')
        selected=self.select_answer(state)
        prediction=None
        if selected is not None:
            prediction=self.scorer.predict([dict(question=state.question,evidence=state.evidence,
                answer=state.successful_models[selected],model_name=selected)])[0]
        # Never replace absent service probability with benchmark proxy probability.
        s=PlanningState(history=tuple((m,v.value if hasattr(v,'value') else v) for m,v in state.attempted_models.items()),
            remaining_time=state.remaining_time,remaining_cost=state.remaining_budget,
            quality=prediction['predicted_quality'] if prediction else 0.,
            pass_probability=prediction.get('service_pass_probability') if prediction else None,
            has_answer=selected is not None,allowed=tuple(state.allowed_models),
            bandwidth=state.environment.get('bandwidth_mbps',0.))
        options=dict(deadline=state.deadline,budget=state.budget,quality_gate=state.quality_threshold)
        options.update(self.options)
        # Factory receives only current question/evidence; future caches are not supplied.
        planner=FinitePlanner(self.provider_factory(state.question,state.evidence),**options)
        result=planner.plan(s);self.plans.append(result)
        action=result['action']
        if action.startswith('CALL:'):return ActionDecision(ActionType.CALL,action[5:],result['reason'])
        return ActionDecision(ActionType(action),reason=result['reason'])

class JointLibraryProvider:
    """Explicit mapping bridge. Caller must supply audited current-task mapper.

    No default mapping: donor predicted_quality is NOT current-task quality.
    Mapper sees only outcome, not donor ID or offline reference labels.
    """
    def __init__(self,library,query_builder,outcome_mapper,request_id,seed=20261015):
        self.library=library;self.query_builder=query_builder;self.mapper=outcome_mapper
        self.request_id=request_id;self.seed=seed
    def __call__(self,state,action):
        from .planner import Scenario
        query=self.query_builder(state,action)
        result=self.library.sample(query,self.request_id,self.seed)
        if not result['supported']:return []
        scenarios=[]
        for s in result['scenarios']:
            o=s['outcome']
            if o['latency_s']>state.remaining_time or o['cost']>state.remaining_cost:return []
            child=self.mapper(state,action,o)
            if child is None:return [] # Explicit unsupported current-task mapping.
            scenarios.append(Scenario(s['weight'],child,o['latency_s'],o['cost']))
        return scenarios
