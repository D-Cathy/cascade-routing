"""Frozen quality regressor and BENCHMARK-score pass proxy classifier."""
from pathlib import Path
import json
import joblib
import numpy as np
import sklearn
from threadpoolctl import threadpool_limits
from sklearn.ensemble import HistGradientBoostingRegressor,HistGradientBoostingClassifier
from .features import ProxyFeatures
from ..routerbench_adapter import digest

class ProxyScorer:
    def __init__(self,threshold=.8):
        if not 0<=threshold<=1:raise ValueError('Invalid threshold')
        self.threshold=threshold;self.features=ProxyFeatures();self.regressor=None;self.classifier=None;self.constant=None

    def fit(self,observations,qualities):
        if self.regressor is not None:raise ValueError('Scorer already frozen; create a new version')
        y=np.asarray(qualities,dtype=float)
        if len(y)!=len(observations) or not np.all(np.isfinite(y)) or np.any((y<0)|(y>1)):raise ValueError('Invalid quality targets')
        with threadpool_limits(limits=1):
            x=self.features.fit(observations).transform(observations)
            args=dict(max_iter=50,max_depth=3,min_samples_leaf=5,early_stopping=False,random_state=20261014)
            self.regressor=HistGradientBoostingRegressor(loss='squared_error',**args).fit(x,y)
            target=(y>=self.threshold).astype(int)
            if len(set(target))==1:self.constant=float(target[0])
            else:self.classifier=HistGradientBoostingClassifier(**args).fit(x,target)
        return self

    def predict(self,observations):
        if self.regressor is None:raise ValueError('Scorer not fitted')
        if not observations:return []
        with threadpool_limits(limits=1):
            x=self.features.transform(observations)
            quality=np.clip(self.regressor.predict(x),0,1)
            probability=np.full(len(x),self.constant) if self.classifier is None else self.classifier.predict_proba(x)[:,1]
        return [{'predicted_quality':float(q) if r['answer'].strip() else 0.0,
                 'proxy_score_pass_probability':float(p) if r['answer'].strip() else 0.0,
                 'service_pass_probability':None} for r,q,p in zip(observations,quality,probability)]

    def save(self,directory,metadata):
        if self.regressor is None:raise ValueError('Scorer not fitted')
        out=Path(directory);out.mkdir(parents=True,exist_ok=False)
        joblib.dump(self,out/'scorer.joblib')
        manifest=dict(metadata)
        manifest.update(artifact_sha256=digest(out/'scorer.joblib'),sklearn_version=sklearn.__version__,
            feature_encoder='char2-4 hashing256, first512 Unicode characters per field, training-only PCA<=32',
            classifier_target='benchmark_quality>=threshold; validity_not_included',
            formal_v5_scorer=False,risk_guarantee=False,threshold=self.threshold,
            pca_dimensions=[self.features.question_pca.n_components_,self.features.answer_pca.n_components_])
        (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')

def load_scorer(directory):
    """Only load trusted locally produced joblib files; hashes are not signatures."""
    p=Path(directory);m=json.loads((p/'manifest.json').read_text())
    if digest(p/'scorer.joblib')!=m['artifact_sha256']:raise ValueError('Scorer hash mismatch')
    if m['sklearn_version']!=sklearn.__version__:raise ValueError('Scikit-learn version mismatch')
    model=joblib.load(p/'scorer.joblib')
    if not isinstance(model,ProxyScorer):raise ValueError('Unexpected scorer type')
    return model,m
