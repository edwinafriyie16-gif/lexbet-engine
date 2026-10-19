#!/usr/bin/env python3
from __future__ import annotations
import json, pickle, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from sklearn.metrics import log_loss
from lexbet.data import connect, build_features
from lexbet.model import remove_margin
from train import fit_classifier, calibrate, calibrated

ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'data/lexbet.sqlite'; ART=ROOT/'artifacts'; REPORT=ROOT/'reports'; REPORT.mkdir(exist_ok=True)

def main():
    conn=connect(DB); raw=pd.read_sql_query("select * from matches where home_goals is not null and away_goals is not null order by kickoff",conn); frame=build_features(raw); frame.kickoff=pd.to_datetime(frame.kickoff,utc=True)
    cutoff=frame.kickoff.max()-pd.Timedelta('183D'); test=frame[frame.kickoff>=cutoff].copy(); folds=pd.date_range(cutoff.normalize(),frame.kickoff.max().normalize(),freq='MS',tz='UTC').tolist(); folds=[cutoff]+[x for x in folds if x>cutoff]
    all_p1=[]; all_y1=[]; bets=[]; returns=[]
    for i,start in enumerate(folds):
        end=folds[i+1] if i+1<len(folds) else frame.kickoff.max()+pd.Timedelta('1s'); fold=test[(test.kickoff>=start)&(test.kickoff<end)]
        prior=frame[frame.kickoff<start]
        if len(prior)<300 or fold.empty: continue
        val_n=max(100,int(len(prior)*.2)); train, val=prior.iloc[:-val_n], prior.iloc[-val_n:]
        ytr=train.result.map({'H':0,'D':1,'A':2}); yv=val.result.map({'H':0,'D':1,'A':2})
        m1=fit_classifier(train,ytr,'multi',[0,1,2]); c1=calibrate(m1,val,yv,[0,1,2])
        y2tr=(train.home_goals+train.away_goals>2.5).astype(int); y2v=(val.home_goals+val.away_goals>2.5).astype(int)
        m2=fit_classifier(train,y2tr,'binary',[0,1]); c2=calibrate(m2,val,y2v,[0,1])
        p1=calibrated(m1,c1,fold); p2=calibrated(m2,c2,fold); labels1=fold.result.map({'H':0,'D':1,'A':2}).to_numpy(); labels2=(fold.home_goals+fold.away_goals>2.5).astype(int).to_numpy()
        all_p1.append(p1); all_y1.append(labels1)
        for j,(_,r) in enumerate(fold.iterrows()):
            if pd.notna(r.odds_home) and pd.notna(r.odds_draw) and pd.notna(r.odds_away):
                prices=[float(r.odds_home),float(r.odds_draw),float(r.odds_away)]; mp=remove_margin(prices); bp=(p1[j]+mp)/2; bp=bp/bp.sum()
                for k,sel in enumerate(['H','D','A']):
                    edge=float(bp[k]-mp[k]); close=[r.closing_home,r.closing_draw,r.closing_away][k]; close=float(close) if pd.notna(close) else prices[k]
                    if .02<=edge<=.08: bets.append({'market':'1X2','selection':sel,'prob':float(bp[k]),'odds':prices[k],'won':int(labels1[j]==k),'clv':(1/prices[k])-(1/close)}); returns.append((prices[k]-1) if labels1[j]==k else -1)
            if pd.notna(r.over25_odds) and pd.notna(r.under25_odds):
                prices=[float(r.over25_odds),float(r.under25_odds)]; mp=remove_margin(prices); bp=(p2[j]+mp)/2; bp=bp/bp.sum()
                for k,sel in enumerate(['O','U']):
                    edge=float(bp[k]-mp[k]);
                    if .02<=edge<=.08: bets.append({'market':'OU25','selection':sel,'prob':float(bp[k]),'odds':prices[k],'won':int(labels2[j]==(1 if k==0 else 0)),'clv':0.0}); returns.append((prices[k]-1) if labels2[j]==(1 if k==0 else 0) else -1)
    p1=np.vstack(all_p1); y1=np.concatenate(all_y1); rel=pd.DataFrame({'prob':p1.max(axis=1),'outcome':(p1.argmax(axis=1)==y1).astype(int)}); rel['bin']=pd.cut(rel.prob,np.linspace(0,1,11),include_lowest=True); curve=rel.groupby('bin',observed=True).agg(mean_pred=('prob','mean'),fraction_positive=('outcome','mean'),count=('outcome','size')).reset_index(); curve.to_csv(REPORT/'reliability_curve.csv',index=False)
    import matplotlib.pyplot as plt
    plt.figure(figsize=(5,5)); plt.plot(curve.mean_pred,curve.fraction_positive,'o-',label='Observed'); plt.plot([0,1],[0,1],'--',label='Perfect'); plt.xlabel('Mean predicted probability'); plt.ylabel('Observed frequency'); plt.title('1X2 reliability curve — expanding walk-forward'); plt.legend(); plt.tight_layout(); plt.savefig(REPORT/'reliability_curve.png',dpi=150); plt.close()
    metrics={'window_start':str(cutoff),'window_end':str(frame.kickoff.max()),'n_matches':len(test),'n_folds':len(all_p1),'n_bets':len(bets),'roi':float(np.sum(returns)/len(returns)) if returns else 0.0,'hit_rate':float(np.mean([x['won'] for x in bets])) if bets else 0.0,'brier_score_1x2':float(np.mean(np.sum((p1-np.eye(3)[y1])**2,axis=1))),'log_loss_1x2':float(log_loss(y1,p1)),'closing_line_value':float(np.mean([x['clv'] for x in bets])) if bets else 0.0,'note':'ROI is a realized historical result, not a guarantee. No tuning was performed to force profit.'}
    (REPORT/'backtest.json').write_text(json.dumps(metrics,indent=2)); conn.execute("insert or replace into backtest_runs (id,market,train_end,validation_end,test_start,test_end,metrics_json,report_path) values (?,?,?,?,?,?,?,?)",('latest','1X2+OU25','expanding','validation-only',str(cutoff),str(frame.kickoff.max()),json.dumps(metrics),str(REPORT/'backtest.json'))); conn.commit(); print(json.dumps(metrics,indent=2))

if __name__=='__main__': main()
