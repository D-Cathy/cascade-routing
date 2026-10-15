"""Offline proxy encoder; explicitly NOT the paper's pretrained token encoder."""
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.decomposition import PCA

ROLES=('ship','shore','cloud')

class ProxyFeatures:
    def __init__(self):
        self.encoder=HashingVectorizer(analyzer='char',ngram_range=(2,4),n_features=256,alternate_sign=False)
        self.question_pca=None;self.answer_pca=None

    def raw(self, rows):
        for r in rows:
            if set(r)!={'question','evidence','answer','model_name'}:raise ValueError('Only observable feature fields accepted')
            if r['model_name'] not in ROLES:raise ValueError('Unknown model role')
            if any(not isinstance(r[k],str) for k in ['question','evidence','answer']):raise ValueError('Text features must be strings')
        q=[(r['question']+'\n'+r['evidence'])[:512] for r in rows]
        a=[r['answer'][:512] for r in rows]
        extra=np.array([[float(r['model_name']==n) for n in ROLES]+[np.log1p(len(r['question'])),np.log1p(len(r['answer'])),float(not r['answer'].strip())] for r in rows])
        return self.encoder.transform(q).toarray(),self.encoder.transform(a).toarray(),extra

    def fit(self,rows):
        if self.question_pca is not None:raise ValueError('Features already frozen')
        if len(rows)<2:raise ValueError('At least two training rows required')
        q,a,_=self.raw(rows)
        # Reduced dimensionality bounded by nonzero training rank.
        nq=max(1,min(32,len(rows)-1,int(np.linalg.matrix_rank(q-q.mean(axis=0)))))
        na=max(1,min(32,len(rows)-1,int(np.linalg.matrix_rank(a-a.mean(axis=0)))))
        self.question_pca=PCA(n_components=nq,svd_solver='full').fit(q)
        self.answer_pca=PCA(n_components=na,svd_solver='full').fit(a)
        return self

    def transform(self,rows):
        if self.question_pca is None:raise ValueError('Features not fitted')
        q,a,e=self.raw(rows)
        return np.hstack([self.question_pca.transform(q),self.answer_pca.transform(a),e])
