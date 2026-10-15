"""Only score already returned, structurally valid answers."""
from ..policies import FixedOrderPolicy
from ..schema import ActionDecision,ActionType

class PredictedThresholdProxy(FixedOrderPolicy):
    def __init__(self,scorer):
        super().__init__(['ship','shore','cloud']);self.scorer=scorer

    def estimate(self,state,model):
        if model not in state.successful_models:raise ValueError('Cannot score uncalled or invalid answer')
        r=dict(question=state.question,evidence=state.evidence,answer=state.successful_models[model],model_name=model)
        return self.scorer.predict([r])[0]['predicted_quality']

    def select_answer(self,state):
        # Dict order is return order: stable max retains earliest on a tie.
        return max(state.successful_models,key=lambda m:self.estimate(state,m),default=None)

    def decide(self,state):
        if state.current_best_answer is not None and state.current_best_quality>=self.scorer.threshold:
            return ActionDecision(ActionType.ACCEPT,reason='proxy_predicted_quality_threshold')
        return super().decide(state)
