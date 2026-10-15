"""Action-conditional signed gain regressors; targets stay offline."""
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

ROLES=('ship','shore','cloud')

def retained_gain(before,after,labels):
    """IDs must come from the SAME frozen predicted selector, not label argmax."""
    def quality(name):
        if name is None:return 0.0
        q=labels.get(name)
        if q is None or not np.isfinite(q) or not 0<=q<=1:raise ValueError('Missing/invalid reference quality')
        return float(q)
    return quality(after)-quality(before)

class GainModels:
    def __init__(self):self.models={};self.dimension=None
    def fit(self,rows):
        if self.models:raise ValueError('Gain models already frozen')
        if not rows:raise ValueError('No training transitions')
        if any(r['action'] not in ROLES for r in rows):raise ValueError('Unknown training action')
        self.dimension=len(rows[0]['features'])
        with threadpool_limits(limits=1):
            for action in ROLES:
                selected=[r for r in rows if r['action']==action]
                if not selected:continue
                x=np.asarray([r['features'] for r in selected],dtype=float);y=np.asarray([r['gain_target'] for r in selected],dtype=float)
                if x.shape!=(len(selected),self.dimension) or not np.isfinite(x).all() or not np.isfinite(y).all() or np.any(abs(y)>1):raise ValueError('Invalid gain training data')
                # Equal weight per source group within action, independent of row count.
                counts={g:sum(r['source_group_id']==g for r in selected) for g in {r['source_group_id'] for r in selected}}
                weights=np.array([1/counts[r['source_group_id']] for r in selected]);weights*=len(weights)/weights.sum()
                model=HistGradientBoostingRegressor(max_iter=50,max_depth=3,min_samples_leaf=2,early_stopping=False,random_state=20261014)
                self.models[action]=model.fit(x,y,sample_weight=weights)
        if not self.models:raise ValueError('No known action')
        return self
    def predict(self,features,allowed):
        if not self.models:raise ValueError('Gain models not fitted')
        x=np.asarray(features,dtype=float)
        if x.shape!=(self.dimension,) or not np.isfinite(x).all() or set(allowed)-set(ROLES):raise ValueError('Invalid gain query')
        with threadpool_limits(limits=1):
            values=[float(np.clip(self.models[a].predict(x[None,:])[0],-1,1)) if a in allowed and a in self.models else 0.0 for a in ROLES]
        return {'gain_vector':values,'action_mask':[a in allowed and a in self.models for a in ROLES]}
