from __future__ import annotations
import json, os, re, sqlite3
from pathlib import Path
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.getenv('LEXBET_DB_PATH', ROOT / 'data' / 'lexbet.sqlite'))

def _rows():
    if DB.exists():
        conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT home_team, away_team, market, selection, odds, model_prob, market_prob, blended_prob, confidence, rationale, risks, alternatives FROM picks WHERE status='open' AND kickoff > datetime('now') ORDER BY blended_prob DESC LIMIT 50").fetchall(); conn.close()
        out=[]
        for row in rows:
            item=dict(row)
            item['display_selection'] = {'Home': item['home_team'], 'Away': item['away_team'], 'O': 'Over 2.5', 'U': 'Under 2.5'}.get(item['selection'], item['selection'])
            out.append(item)
        if out: return out
    return _live_market_rows()

def _live_market_rows():
    """Use bookmaker consensus as a transparent hosted fallback when SQLite is absent."""
    key=os.getenv('ODDS_API_KEY')
    if not key: return []
    try:
        query=urlencode({'apiKey':key,'regions':'uk,eu','markets':'h2h','oddsFormat':'decimal'})
        req=Request(f'https://api.the-odds-api.com/v4/sports/soccer_epl/odds?{query}', headers={'User-Agent':'lexbet-chat/1.0'})
        with urlopen(req, timeout=12) as response: events=json.loads(response.read())
    except Exception:
        return []
    out=[]
    for event in events:
        prices={}
        for book in event.get('bookmakers',[]):
            for market in book.get('markets',[]):
                if market.get('key') != 'h2h': continue
                for outcome in market.get('outcomes',[]): prices.setdefault(outcome.get('name'),[]).append(float(outcome['price']))
        if len(prices) < 3: continue
        names=list(prices); avg=[sum(prices[n])/len(prices[n]) for n in names]; inv=[1/p for p in avg]; total=sum(inv)
        probs=[p/total for p in inv]; idx=max(range(len(names)), key=lambda i:probs[i]); name=names[idx]; prob=probs[idx]
        home=event.get('home_team','Home'); away=event.get('away_team','Away')
        selection='Home' if name==home else 'Away' if name==away else 'Draw'
        out.append({'home_team':home,'away_team':away,'market':'1X2','selection':selection,'display_selection':name,'odds':avg[idx], 'model_prob':prob, 'market_prob':prob, 'blended_prob':prob, 'confidence':'Market consensus', 'rationale':f"The strongest de-vigged bookmaker consensus is {prob:.1%} for {name}. This hosted fallback uses market data only because the trained local model is not connected.", 'risks':'Market consensus is not a guarantee; check lineups, injuries, rotation, and kickoff time.', 'alternatives':'Ask why the draw or the other team is not selected; disagreement with the market is a reason to pause.'})
    return sorted(out, key=lambda x:x['blended_prob'], reverse=True)[:50]

def _number(text):
    m=re.search(r'\b([1-9]|[1-4][0-9])\b', text)
    return int(m.group(1)) if m else 5

def answer(message):
    text=message.lower(); rows=_rows(); n=_number(text)
    if not rows:
        return {'reply':'I do not have fresh open recommendations yet. Run the daily refresh, train the model, then run scripts/predict.py so the desk has today’s fixtures and odds.', 'picks':[], 'count':0}
    if any(word in text for word in ['best','safest','odds','today','picks','recommend']):
        picks=rows[:n]
        return {'reply':f"Here are the {len(picks)} strongest likely outcomes currently on the desk. I ranked them by estimated likelihood, not by edge. Challenge the risk note on each one.", 'picks':picks, 'count':len(picks)}
    match=next((r for r in rows if r['home_team'].lower() in text or r['away_team'].lower() in text), None)
    if match:
        return {'reply':f"Here is the case for {match['home_team']} v {match['away_team']}. Ask me to challenge any part of it.", 'picks':[match], 'count':1}
    if 'why' in text or 'risk' in text or 'debate' in text:
        return {'reply':'Pick a match or ask “give me the best 5 odds today.” Each card includes the evidence, main risk, and strongest alternative so you can debate the call.', 'picks':rows[:3], 'count':min(3,len(rows))}
    return {'reply':'Try “give me the best 5 odds today”, “show me the safest picks”, or ask “why Barcelona?” The desk ranks likely outcomes and explains the reasoning.', 'picks':[], 'count':len(rows)}

def handle_request(request):
    if request.method != 'POST':
        return {'statusCode':405,'headers':{'Content-Type':'application/json'},'body':json.dumps({'error':'POST a JSON message'})}
    try: payload=json.loads(request.body or '{}')
    except Exception: payload={}
    result=answer(str(payload.get('message','')))
    return {'statusCode':200,'headers':{'Content-Type':'application/json','Cache-Control':'no-store'},'body':json.dumps(result)}

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        result = handle_request(type('Request', (), {
            'method': 'POST',
            'body': self.rfile.read(int(self.headers.get('Content-Length', '0'))),
        })())
        body = result['body'].encode()
        self.send_response(result['statusCode'])
        for key, value in result.get('headers', {}).items(): self.send_header(key, value)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.send_response(405)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(b'{"error":"POST a JSON message"}')
