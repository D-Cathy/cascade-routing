"""Restricted adapter around the ORIGINAL CascadeRouter, with engineering-only priors.
No GroundTruth estimator, no per-evaluation-task lookup. Fitted means are intentionally
weak and must not be described as the paper's trained estimator reproduction.
"""
import numpy as np
from .cascade_router import CascadeRouter
from .quality_computer import BaseQualityComputer
from .cost_computer import BaseCostComputer
from .schema import ActionDecision, ActionType

FAILED_OBSERVATION = object()

class DevelopmentMeanQuality(BaseQualityComputer):
    def __init__(self, means):
        super().__init__()
        self.means = np.array(means, dtype=float)
    def predict(self, questions, model_answers):
        values = np.tile(self.means, (len(questions), 1))
        for i, answers in enumerate(model_answers):
            for j, answer in enumerate(answers):
                if answer is FAILED_OBSERVATION:
                    values[i,j] = -1e6
        return values, [None for _ in questions]

class DevelopmentMeanCost(BaseCostComputer):
    def __init__(self, means):
        super().__init__()
        self.means = np.array(means, dtype=float)
    def predict(self, questions, model_answers):
        return np.tile(self.means, (len(questions), 1))

class CascadeRouterAdapter:
    def __init__(self, router):
        if router.lambdas is None or router.gamma is None:
            raise ValueError("CascadeRouter must be fitted before adapter use")
        if not isinstance(router.quality_computer, DevelopmentMeanQuality) or not isinstance(router.cost_computer, DevelopmentMeanCost):
            raise ValueError("This engineering adapter currently supports development-mean estimators only")
        self.router = router
        self.predict_calls = 0
    @classmethod
    def fit_development_means(cls, model_names, qualities, costs, max_expected_cost=100.0):
        # Caller enforces task AND source-group separation; no evaluation data here.
        q, c = np.asarray(qualities, dtype=float), np.asarray(costs, dtype=float)
        if q.ndim != 2 or q.shape != c.shape or q.shape[1] != len(model_names) or not len(q):
            raise ValueError("Invalid fitting matrix")
        if not np.isfinite(q).all() or not np.isfinite(c).all() or (q<0).any() or (q>1).any() or (c<0).any():
            raise ValueError("Fitting labels/resources must be observed and finite")
        router = CascadeRouter(DevelopmentMeanQuality(q.mean(axis=0)), DevelopmentMeanCost(c.mean(axis=0)),
                               list(model_names), max_expected_cost, strategies=[], force_order=True, cascade=False)
        # Zero lambda is a predeclared engineering configuration, not a tuned baseline.
        router.fit([f"fit-{i}" for i in range(len(q))], [["fit-answer"]*len(model_names) for _ in q],
                   ground_truth_qualities=q, ground_truth_costs=c)
        return cls(router)
    def estimate(self, state, model):
        return self.router.quality_computer.means[self.router.models.index(model)]
    def select_answer(self, state):
        answers = [state.successful_models.get(n) for n in self.router.models]
        return self.router.select_answer([state.question], [answers])[0]
    def decide(self, state):
        if not state.allowed_models:
            return ActionDecision(ActionType.ACCEPT, reason="no_legal_upgrade")
        # Restrict the action pool, retaining failed attempts as non-None observations
        # so the original step counter and upward-only order cannot retry them.
        names = [n for n in self.router.models if n in state.allowed_models or n in state.attempted_models]
        indices = [self.router.models.index(n) for n in names]
        restricted = CascadeRouter(DevelopmentMeanQuality(self.router.quality_computer.means[indices]),
                                   DevelopmentMeanCost(self.router.cost_computer.means[indices]), names,
                                   self.router.max_expected_cost, strategies=[], force_order=True, cascade=False)
        restricted.lambdas = self.router.lambdas[:len(names)]
        restricted.gamma = self.router.gamma
        answers = [state.successful_models.get(n, FAILED_OBSERVATION) if n in state.attempted_models else None for n in names]
        self.predict_calls += 1
        model = restricted.predict([state.question], [answers])[0]
        if model is None:
            return ActionDecision(ActionType.ACCEPT, reason="original_cascade_router_stop")
        if model not in state.allowed_models:
            raise ValueError("Original baseline proposed an illegal model")
        return ActionDecision(ActionType.CALL, model, "original_cascade_router_predict")
