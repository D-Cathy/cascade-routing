from .schema import ActionDecision, ActionType

class FixedOrderPolicy:
    """Exhaust a predeclared order, then return latest valid answer (no predictor)."""
    def __init__(self, order):
        self.order = list(order)
    def decide(self, state):
        name = self.next_model(state)
        return ActionDecision(ActionType.CALL, name) if name else ActionDecision(ActionType.ACCEPT, reason="fixed_order_exhausted")
    def next_model(self, state):
        return next((n for n in self.order if n in state.allowed_models and n not in state.attempted_models), None)

class ThresholdPolicy(FixedOrderPolicy):
    """Without a predictor, explicitly fall back to exhausting the fixed order."""
    def __init__(self, threshold, order, scorer=None):
        super().__init__(order)
        self.threshold, self.scorer = threshold, scorer
    def estimate(self, state, model):
        return self.scorer(state, model) if self.scorer else -1.0
    def decide(self, state):
        if state.current_best_answer is not None and state.current_quality_estimate is not None and state.current_quality_estimate >= self.threshold:
            return ActionDecision(ActionType.ACCEPT, reason="predicted_threshold")
        return super().decide(state)
