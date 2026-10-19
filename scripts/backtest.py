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
from train import calibrated

ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'data/lexbet.sqlite'; ART=ROOT/'artifacts'; REPORT=ROOT/'reports'; REPORT.mkdir(exist_ok=True)

def main():
    with open(ART/'models.pkl','rb') as f: b=pickle.load(f)
    conn=connect(DB); raw=pd.read_sql_query("select * from matches where home_goals is not null and away_goals is not null order by kickoff",conn); frame=build_features(raw)
    cutoff=pd.to_datetime(frame.kickoff,utc=True).max()-pd.Timedelta(days=183); test=frame[pd.to_datetime(frame.kickoff,utc=True)>=cutoff].copy()
    p1=calibrated(b['model_1x2'],b['cal_1x2'],test); p2=calibrated(b['model_ou25'],b['cal_ou25'],test)
    labels1=test.result.map({'H':0,'D':1,'A':2}).to_numpy(); labels2=(test.home_goals+test.away_goals>2.5).astype(int).to_numpy()
    bets=[]; returns=[]
    for i,(_,r) in enumerate(test.iterrows()):
        if pd.notna(r.odds_home) and pd.notna(r.odds_draw) and pd.notna(r.odds_away):
            mp=remove_margin([r.odds_home,r.odds_draw,r.odds_away]); bp=.5*p1[i]+.5*mp; bp=bp/bp.sum()
            for j,sel in enumerate(['H','D','A']):
                edge=float(bp[j]-mp[j]); odds=float([r.odds_home,r.odds_draw,r.odds_away][j])
                if .02<=edge<=.08:
                    won=int(labels1[i]==j); ret=(odds-1) if won else -1; close=float([r.closing_home,r.closing_draw,r.closing_away][j]) if pd.notna([r.closing_home,r.closing_draw,r.closing_away][j]) else odds
                    bets.append({'market':'1X2','selection':sel,'prob':float(bp[j]),'market_prob':float(mp[j]),'odds':odds,'won':won,'clv':float((1/odds)-(1/close))}); returns.append(ret)
        if pd.notna(r.over25_odds) and pd.notna(r.under25_odds):
            mp=remove_margin([r.over25_odds,r.under25_odds]); bp=.5*p2[i]+.5*mp; bp=bp/bp.sum()
            for j,sel in enumerate(['O','U']):
                edge=float(bp[j]-mp[j]); odds=float([r.over25_odds,r.under25_odds][j])
                if .02<=edge<=.08:
                    won=int(labels2[i]==(0 if sel=='U' else 1)); bets.append({'market':'OU25','selection':sel,'prob':float(bp[j]),'market_prob':float(mp[j]),'odds':odds,'won':won,'clv':0.0}); returns.append((odds-1) if won else -1)
    yprob=np.concatenate([p1[:,0],p1[:,1],p1[:,2]]) if False else p1
    rel=pd.DataFrame({'prob':p1.max(axis=1),'outcome':(p1.argmax(axis=1)==labels1).astype(int)}); rel['bin']=pd.cut(rel.prob,np.linspace(0,1,11),include_lowest=True); curve=rel.groupby('bin',observed=True).agg(mean_pred=('prob','mean'),fraction_positive=('outcome','mean'),count=('outcome','size')).reset_index(); curve.to_csv(REPORT/'reliability_curve.csv',index=False)
    import matplotlib.pyplot as plt
    plt.figure(figsize=(5,5)); plt.plot(curve.mean_pred,curve.fraction_positive,'o-',label='Observed'); plt.plot([0,1],[0,1],'--',label='Perfect'); plt.xlabel('Mean predicted probability'); plt.ylabel('Observed frequency'); plt.title('1X2 reliability curve — six-month test'); plt.legend(); plt.tight_layout(); plt.savefig(REPORT/'reliability_curve.png',dpi=150); plt.close()
    metrics={'window_start':str(cutoff),'window_end':str(frame.kickoff.max()),'n_matches':len(test),'n_bets':len(bets),'roi':float(np.sum(returns)/len(returns)) if returns else 0.0,'hit_rate':float(np.mean([x['won'] for x in bets])) if bets else 0.0,'brier_score_1x2':float(np.mean(np.sum((p1-np.eye(3)[labels1])**2,axis=1))),'log_loss_1x2':float(log_loss(labels1,p1)),'closing_line_value':float(np.mean([x['clv'] for x in bets])) if bets else 0.0,'note':'ROI is a realized historical result, not a guarantee. No tuning was performed to force profit.'}
    (REPORT/'backtest.json').write_text(json.dumps(metrics,indent=2)); conn.execute("insert or replace into backtest_runs (id,market,train_end,validation_end,test_start,test_end,metrics_json,report_path) values (?,?,?,?,?,?,?,?)",('latest','1X2+OU25',b['train_end'],b['validation_end'],str(cutoff),str(frame.kickoff.max()),json.dumps(metrics),str(REPORT/'backtest.json'))); conn.commit(); print(json.dumps(metrics,indent=2))

if __name__=='__main__': main()
