#!/usr/bin/env python3
from __future__ import annotations
import json, os, sqlite3
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data/lexbet.sqlite'

def main():
    token=os.environ.get('TELEGRAM_BOT_TOKEN'); chat_id=os.environ.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        print('Telegram delivery skipped: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required.'); return
    conn=sqlite3.connect(DB); conn.row_factory=sqlite3.Row
    picks=[dict(r) for r in conn.execute("select * from picks where status='open' and kickoff > datetime('now') order by kickoff").fetchall()]
    run=conn.execute("select metrics_json from backtest_runs order by created_at desc limit 1").fetchone()
    paper=conn.execute("select count(*) n, coalesce(sum(profit),0) profit from paper_trades where settled_at is not null").fetchone(); conn.close()
    lines=['Lexbet daily paper picks','Not guaranteed. Paper-trading only.']
    if picks:
        for p in picks: lines.append(f"{p['home_team']} v {p['away_team']} — {p['market']} {p['selection']} @ {p['odds']:.2f}; p={p['blended_prob']:.1%}; edge={p['edge']:.1%}; stake={p['stake']:.2f}")
    else: lines.append('No qualifying picks. No bet is a valid outcome.')
    if run:
        m=json.loads(run[0]); lines.append(f"Backtest ROI: {m.get('roi',0):.2%}; bets: {m.get('n_bets',0)}; paper settled profit: {paper['profit']:.2f} ({paper['n']} trades)")
    r=requests.post(f'https://api.telegram.org/bot{token}/sendMessage',json={'chat_id':chat_id,'text':'\n'.join(lines)},timeout=30); r.raise_for_status(); print('Telegram message sent.')
if __name__=='__main__': main()
