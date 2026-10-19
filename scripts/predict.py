#!/usr/bin/env python3
from __future__ import annotations
import hashlib, os, pickle, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np, pandas as pd
from dotenv import load_dotenv
from lexbet.data import connect, build_features, insert_odds, insert_picks
from lexbet.model import remove_margin, fractional_kelly
from lexbet.providers import fetch_live_odds, normalise_odds
from train import calibrated
ROOT=Path(__file__).resolve().parents[1]; DB=ROOT/'data/lexbet.sqlite'; ART=ROOT/'artifacts'

def main():
    load_dotenv();
    with open(ART/'models.pkl','rb') as f: b=pickle.load(f)
    try:
        payload=fetch_live_odds()
    except RuntimeError as exc:
        print(f"live prediction unavailable: {exc}"); return
    odds=normalise_odds(payload); conn=connect(DB); insert_odds(conn,odds)
    if odds.empty: print('No upcoming odds returned.'); return
    hist=pd.read_sql_query("select * from matches where home_goals is not null and away_goals is not null order by kickoff",conn)
    bankroll=float(os.getenv('LEXBET_BANKROLL','1000')); picks=[]
    for event_id,g in odds.groupby('event_id'):
        event=g.iloc[0]
        synthetic=hist.iloc[[0]].copy(); synthetic.loc[:, :]=np.nan
        synthetic['home_team']=event.home_team; synthetic['away_team']=event.away_team; synthetic['kickoff']=event.kickoff
        prior=build_features(pd.concat([hist, synthetic], ignore_index=True)).tail(1)
        h2h=g[g.market=='h2h']; totals=g[g.market=='totals']
        if len(h2h)>=3:
            names=['Home','Draw','Away']; prices=[]
            for n in names:
                q=h2h[h2h.selection==n].odds
                if not q.empty: prices.append(float(q.mean()))
            if len(prices)==3:
                raw=calibrated(b['model_1x2'],b['cal_1x2'],prior)[0]; mp=remove_margin(prices); bp=(raw+mp)/2; bp=bp/bp.sum()
                for j,n in enumerate(names):
                    edge=float(bp[j]-mp[j]); price=prices[j]
                    if .02<=edge<=.08:
                        picks.append(_pick(event_id,event,'1X2',n,price,float(raw[j]),float(mp[j]),float(bp[j]),bankroll))
        if len(totals)>=2:
            names=['Over 2.5','Under 2.5']; q=[totals[totals.selection==n].odds for n in names]
            if all(not x.empty for x in q):
                prices=[float(x.mean()) for x in q]; raw=calibrated(b['model_ou25'],b['cal_ou25'],prior)[0]; mp=remove_margin(prices); bp=(raw+mp)/2; bp=bp/bp.sum()
                for j,n in enumerate(names):
                    edge=float(bp[j]-mp[j]);
                    if .02<=edge<=.08: picks.append(_pick(event_id,event,'OU25','O' if j==0 else 'U',prices[j],float(raw[j]),float(mp[j]),float(bp[j]),bankroll))
    insert_picks(conn,picks); print(pd.DataFrame(picks).to_string(index=False) if picks else 'No picks passed the 2–8 pp filter. No bet is a valid outcome.')

def _pick(event_id,event,market,selection,odds,model_prob,market_prob,prob,bankroll):
    return {'id':hashlib.sha256(f'{event_id}|{market}|{selection}'.encode()).hexdigest()[:24],'event_id':event_id,'kickoff':event.kickoff,'home_team':event.home_team,'away_team':event.away_team,'market':market,'selection':selection,'odds':odds,'model_prob':model_prob,'market_prob':market_prob,'blended_prob':prob,'edge':prob-market_prob,'stake':fractional_kelly(prob,odds,bankroll),'bankroll':bankroll}
if __name__=='__main__': main()
