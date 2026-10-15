import math

import pytest

from selection.schema import ModelLevel, ModelStatus, RequestStatus, ServiceFailureReason, ObservableState
from selection.executor import OfflineModel, UnifiedExecutor
from selection.policies import FixedOrderPolicy, ThresholdPolicy
from selection.metrics import summarize_trace


@pytest.fixture
def simple_models():
    return [
        OfflineModel(name='ship', level=ModelLevel.SHIP, latency=1.0, cost=2.0, quality=0.62, fail_probability=0.0),
        OfflineModel(name='shore', level=ModelLevel.SHORE, latency=2.0, cost=4.0, quality=0.86, fail_probability=0.0),
        OfflineModel(name='cloud', level=ModelLevel.CLOUD, latency=5.0, cost=12.0, quality=0.96, fail_probability=0.0),
    ]


def test_successful_accept_stops(simple_models):
    executor = UnifiedExecutor(
        models=simple_models,
        deadline=30.0,
        budget=100.0,
        quality_threshold=0.8,
        decision_overhead=0.1,
        policy=FixedOrderPolicy(order=['ship', 'shore', 'cloud']),
        allow_skip_levels=True,
    )
    trace = executor.execute({'question': 'hello', 'evidence': 'ctx'})
    assert trace.status == RequestStatus.SUCCEEDED
    assert trace.final_answer is not None
    assert trace.model_calls[0].model_name == 'ship'
    assert trace.total_time >= 1.0
    assert trace.total_cost >= 2.0


def test_failed_call_counts_and_prevents_retry(simple_models):
    models = [
        OfflineModel(name='ship', level=ModelLevel.SHIP, latency=1.0, cost=2.0, quality=0.4, fail_probability=1.0),
        OfflineModel(name='shore', level=ModelLevel.SHORE, latency=2.0, cost=4.0, quality=0.9, fail_probability=0.0),
        OfflineModel(name='cloud', level=ModelLevel.CLOUD, latency=4.0, cost=12.0, quality=0.95, fail_probability=0.0),
    ]
    executor = UnifiedExecutor(
        models=models,
        deadline=30.0,
        budget=20.0,
        quality_threshold=0.8,
        decision_overhead=0.1,
        policy=FixedOrderPolicy(order=['ship', 'shore', 'cloud']),
        allow_skip_levels=True,
    )
    trace = executor.execute({'question': 'hello', 'evidence': 'ctx'})
    assert trace.model_calls[0].status == ModelStatus.FAILED
    assert trace.total_cost >= 2.0
    assert trace.model_calls[0].attempted_once is True
    assert len(trace.model_calls) >= 2
    assert any(call.model_name == 'ship' for call in trace.model_calls)
    assert all(call.model_name != 'ship' or call.status == ModelStatus.FAILED for call in trace.model_calls)


def test_downward_or_unknown_call_forbidden(simple_models):
    executor = UnifiedExecutor(
        models=simple_models,
        deadline=10.0,
        budget=100.0,
        quality_threshold=0.8,
        decision_overhead=0.0,
        policy=FixedOrderPolicy(order=['ship', 'shore', 'cloud']),
        allow_skip_levels=True,
    )
    state = ObservableState(
        question='hello',
        evidence='ctx',
        allowed_models=['ship', 'shore', 'cloud'],
        attempted_models={},
        successful_models={},
        failed_models={},
        invalid_models={},
        current_quality_estimate=0.9,
        remaining_time=10.0,
        remaining_budget=100.0,
        current_best_answer='ans',
        current_best_quality=0.9,
    )
    with pytest.raises(ValueError):
        executor._validate_call(state, 'ship', 'ship')

    with pytest.raises(ValueError):
        executor._validate_call(state, 'unknown', 'cloud')

    with pytest.raises(ValueError):
        executor._validate_call(state, 'ship', 'cloud')


def test_no_valid_answer_ends_safely(simple_models):
    models = [
        OfflineModel(name='ship', level=ModelLevel.SHIP, latency=1.0, cost=2.0, quality=0.4, fail_probability=0.0, invalid_after_answer=True),
        OfflineModel(name='shore', level=ModelLevel.SHORE, latency=1.0, cost=2.0, quality=0.4, fail_probability=0.0, invalid_after_answer=True),
        OfflineModel(name='cloud', level=ModelLevel.CLOUD, latency=1.0, cost=2.0, quality=0.4, fail_probability=0.0, invalid_after_answer=True),
    ]
    executor = UnifiedExecutor(
        models=models,
        deadline=30.0,
        budget=100.0,
        quality_threshold=0.8,
        decision_overhead=0.1,
        policy=FixedOrderPolicy(order=['ship', 'shore', 'cloud']),
        allow_skip_levels=True,
    )
    trace = executor.execute({'question': 'hello', 'evidence': 'ctx'})
    assert trace.status == RequestStatus.FAILED
    assert ServiceFailureReason.NO_VALID_ANSWER in trace.failure_reasons


def test_controller_does_not_get_hidden_labels():
    state = ObservableState(
        question='hello',
        evidence='ctx',
        allowed_models=['ship', 'shore'],
        attempted_models={},
        successful_models={},
        failed_models={},
        invalid_models={},
        current_quality_estimate=0.7,
        remaining_time=10.0,
        remaining_budget=10.0,
        current_best_answer='ans',
        current_best_quality=0.7,
    )
    observable = state.to_observable_dict()
    assert not hasattr(state, 'hidden_quality_labels')
    assert 'hidden_quality_labels' not in observable
    assert 'hidden_future_answers' not in observable
    assert 'hidden_environment' not in observable


def test_select_answer_safe_for_empty_history():
    from selection.router import CascadeRouter
    from selection.quality_computer import GroundTruthQualityComputer
    from selection.cost_computer import GroundTruthCostComputer

    quality = GroundTruthQualityComputer()
    cost = GroundTruthCostComputer(noise_before_run=0.0, noise_after_run=0.0)
    router = CascadeRouter(
        quality,
        cost,
        models=['ship', 'shore', 'cloud'],
        max_expected_cost=100.0,
        strategies=[],
        force_order=True,
        cascade=False,
    )
    out = router.select_answer([['hello']], [[None, None, None]])
    assert out == [None]


def test_summary_metrics_are_consistent(simple_models):
    executor = UnifiedExecutor(
        models=simple_models,
        deadline=30.0,
        budget=100.0,
        quality_threshold=0.8,
        decision_overhead=0.1,
        policy=ThresholdPolicy(threshold=0.8, order=['ship', 'shore', 'cloud']),
        allow_skip_levels=True,
    )
    trace = executor.execute({'question': 'hello', 'evidence': 'ctx'})
    summary = summarize_trace(trace)
    assert 'total_cost' in summary
    assert summary['service_failure'] in {True, False}
    assert summary['cumulative_calls'] >= 1
