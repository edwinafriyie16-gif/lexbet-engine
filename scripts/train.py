#!/usr/bin/env python3
from __future__ import annotations
import json, pickle, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from xgboost import XGBClassifier
from lexbet.data import connect, build_features
from lexbet.model import FEATURES

ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'data/lexbet.sqlite'; ART=ROOT/'artifacts'; ART.mkdir(exist_ok=True)

def fit_classifier(X, y, objective, classes):
    params=dict(n_estimators=180,max_depth=3,learning_rate=.04,subsample=.85,colsample_bytree=.85,random_state=42,n_jobs=2,eval_metric='logloss' if len(classes)==2 else 'mlogloss')
    if len(classes)==2: params.update(objective='binary:logistic')
    else: params.update(objective='multi:softprob',num_class=len(classes))
    m=XGBClassifier(**params); m.fit(X[FEATURES], y); return m

def calibrate(model, X, y, classes):
    raw=model.predict_proba(X[FEATURES]); cals=[]
    for i, cls in enumerate(classes): cals.append(IsotonicRegression(out_of_bounds='clip').fit(raw[:,i], (y.to_numpy()==cls).astype(int)))
    return cals

def calibrated(model,cals,X):
    raw=model.predict_proba(X[FEATURES]); out=np.column_stack([c.predict(raw[:,i]) for i,c in enumerate(cals)])
    return out/np.clip(out.sum(axis=1,keepdims=True),1e-12,None)

def load_frame():
    conn=connect(DB); x=pd.read_sql_query("select * from matches where home_goals is not null and away_goals is not null order by kickoff",conn)
    if x.empty: raise SystemExit('No completed matches in data/lexbet.sqlite; run scripts/daily_update.py first.')
    return build_features(x)

def train_bundle(frame):
    n=len(frame); train_end=int(n*.60); val_end=int(n*.80)
    train, val, test=frame.iloc[:train_end], frame.iloc[train_end:val_end], frame.iloc[val_end:]
    Xtr,Xv,Xte=train,val,test
    y1tr=train.result.map({'H':0,'D':1,'A':2}); y1v=val.result.map({'H':0,'D':1,'A':2})
    y2tr=(train.home_goals+train.away_goals>2.5).astype(int); y2v=(val.home_goals+val.away_goals>2.5).astype(int)
    m1=fit_classifier(Xtr,y1tr,'multi',[0,1,2]); c1=calibrate(m1,Xv,y1v,[0,1,2])
    m2=fit_classifier(Xtr,y2tr,'binary',[0,1]); c2=calibrate(m2,Xv,y2v,[0,1])
    bundle={'model_1x2':m1,'cal_1x2':c1,'model_ou25':m2,'cal_ou25':c2,'features':FEATURES,'train_end':str(train.kickoff.iloc[-1]),'validation_end':str(val.kickoff.iloc[-1]),'test_start':str(test.kickoff.iloc[0]),'test_end':str(test.kickoff.iloc[-1])}
    with open(ART/'models.pkl','wb') as f: pickle.dump(bundle,f)
    meta={k:bundle[k] for k in ['train_end','validation_end','test_start','test_end']}; meta.update({'rows':len(frame),'train_rows':len(train),'validation_rows':len(val),'test_rows':len(test)})
    (ART/'training_split.json').write_text(json.dumps(meta,indent=2,default=str))
    print(json.dumps(meta,indent=2)); return bundle, frame, test

if __name__=='__main__': train_bundle(load_frame())
