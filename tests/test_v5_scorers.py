import numpy as np
import pytest
from selection.v5.features import ProxyFeatures
from selection.v5.scorers import ProxyScorer,load_scorer
from selection.v5.selector import PredictedThresholdProxy
from selection.schema import ObservableState

def rows():return [dict(question=f'Question {i}',evidence='fixed',answer=f'Answer {i}',model_name='ship') for i in range(12)]

def fitted(target=None):return ProxyScorer().fit(rows(),target or [0,1]*6)

def test_feature_label_injection_rejected():
    r=rows();r[0]['quality']=1
    with pytest.raises(ValueError):ProxyFeatures().fit(r)

def test_transform_does_not_refit():
    f=ProxyFeatures().fit(rows());before=f.question_pca.components_.copy()
    f.transform([dict(question='unseen vocabulary',evidence='',answer='new answer',model_name='cloud')])
    assert np.array_equal(before,f.question_pca.components_)

def test_frozen_refit_rejected():
    m=fitted()
    with pytest.raises(ValueError):m.fit(rows(),[0,1]*6)

def test_probability_not_service_probability():
    p=fitted().predict(rows())
    assert all(0<=r['predicted_quality']<=1 and 0<=r['proxy_score_pass_probability']<=1 and r['service_pass_probability'] is None for r in p)

@pytest.mark.parametrize('target',[0,1])
def test_single_class_explicit_fallback(target):
    m=fitted([target]*12)
    assert m.classifier is None
    assert all(r['proxy_score_pass_probability']==target for r in m.predict(rows()))

def test_empty_answer_zero():
    r=rows()[0];r['answer']=''
    assert fitted().predict([r])[0]['predicted_quality']==0

def test_roundtrip_and_hash(tmp_path):
    m=fitted();p=tmp_path/'artifact';m.save(p,{})
    restored,_=load_scorer(p);assert m.predict(rows())==restored.predict(rows())
    with (p/'scorer.joblib').open('ab') as f:f.write(b'changed')
    with pytest.raises(ValueError,match='hash'):load_scorer(p)

def test_no_uncalled_answer():
    policy=PredictedThresholdProxy(fitted());state=ObservableState('q','e',['ship'])
    assert policy.select_answer(state) is None
    with pytest.raises(ValueError):policy.estimate(state,'ship')

def test_selector_keeps_best_and_stable_tie():
    class Stub:
        threshold=.8
        def predict(self,rs):return [{'predicted_quality':.9 if r['answer']=='good' else .2} for r in rs]
    p=PredictedThresholdProxy(Stub());s=ObservableState('q','e',[])
    s.successful_models={'ship':'good','shore':'bad','cloud':'good'}
    assert p.select_answer(s)=='ship'

def test_invalid_targets():
    with pytest.raises(ValueError):ProxyScorer().fit(rows(),[float('nan')]*12)
