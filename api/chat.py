from __future__ import annotations
import json, os, re, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DB = Path(os.getenv('LEXBET_DB_PATH', ROOT / 'data' / 'lexbet.sqlite'))

def _rows(include_extra=False):
    if DB.exists():
        conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT home_team, away_team, market, selection, odds, model_prob, market_prob, blended_prob, confidence, rationale, risks, alternatives FROM picks WHERE status='open' AND kickoff > datetime('now') ORDER BY blended_prob DESC LIMIT 50").fetchall(); conn.close()
        out=[]
        for row in rows:
            item=dict(row)
            item['display_selection'] = {'Home': item['home_team'], 'Away': item['away_team'], 'O': 'Over 2.5', 'U': 'Under 2.5'}.get(item['selection'], item['selection'])
            out.append(item)
        if out: return out
    return _live_market_rows(include_extra=include_extra)

def _live_market_rows(include_extra=False):
    """Build today's mixed-market desk from bookmaker consensus when SQLite is absent."""
    key=os.getenv('ODDS_API_KEY')
    if not key: return []
    leagues = os.getenv('LEXBET_ODDS_SPORTS', 'soccer_epl,soccer_spain_la_liga,soccer_germany_bundesliga,soccer_italy_serie_a,soccer_france_ligue_one,soccer_efl_champ').split(',')
    today = datetime.now(timezone.utc).date()
    events=[]; event_sources=[]
    for sport in [x.strip() for x in leagues if x.strip()]:
        try:
            query=urlencode({'apiKey':key,'regions':'uk,eu','markets':'h2h,totals','oddsFormat':'decimal','dateFormat':'iso'})
            req=Request(f'https://api.the-odds-api.com/v4/sports/{sport}/odds?{query}', headers={'User-Agent':'lexbet-chat/1.0'})
            with urlopen(req, timeout=12) as response:
                batch=json.loads(response.read()); events.extend(batch); event_sources.extend((sport,e) for e in batch)
        except Exception:
            continue
    out=[]; today_events=[]
    for event in events:
        try:
            kickoff=datetime.fromisoformat(event.get('commence_time','').replace('Z','+00:00'))
            if kickoff.astimezone(timezone.utc).date() != today: continue
        except Exception:
            continue
        home=event.get('home_team','Home'); away=event.get('away_team','Away')
        today_events.append(event)
        prices={}
        for book in event.get('bookmakers',[]):
            for market in book.get('markets',[]):
                mkey=market.get('key')
                for outcome in market.get('outcomes',[]):
                    name=outcome.get('name'); point=outcome.get('point')
                    if not name or not outcome.get('price'): continue
                    if mkey == 'totals' and point not in (2.5, '2.5'): continue
                    prices.setdefault((mkey,name),[]).append(float(outcome['price']))
        for market_key in ('h2h','totals'):
            group={name:vals for (mk,name),vals in prices.items() if mk == market_key}
            if market_key == 'h2h' and len(group) < 3: continue
            if market_key == 'totals' and not {'Over','Under'}.issubset(group): continue
            names=list(group); avg=[sum(group[n])/len(group[n]) for n in names]; inv=[1/p for p in avg]; total=sum(inv)
            probs=[p/total for p in inv]; idx=max(range(len(names)), key=lambda i:probs[i]); name=names[idx]; prob=probs[idx]
            if market_key == 'h2h':
                selection='Home' if name==home else 'Away' if name==away else 'Draw'; market='1X2'; display=name
            else:
                selection='O' if name == 'Over' else 'U'; market='OU25'; display=f'{name} 2.5 goals'
            out.append({'home_team':home,'away_team':away,'market':market,'selection':selection,'display_selection':display,'odds':avg[idx], 'model_prob':prob, 'market_prob':prob, 'blended_prob':prob, 'confidence':'Market consensus', 'rationale':f"Today's de-vigged bookmaker consensus is {prob:.1%} for {display}. This hosted fallback uses live market data; the trained local model is not connected.", 'risks':'Market consensus is not a guarantee; check lineups, injuries, rotation, weather, and kickoff time.', 'alternatives':f"The strongest alternative is the other {market} outcome; challenge this pick if team news or match context changes."})
    # Additional SportyBet-style markets are fetched per event because the provider
    # exposes them through the event-odds endpoint rather than the featured feed.
    # Optional markets are expensive on the provider API. Keep them opt-in so
    # the stable daily feed is not exhausted by event-level requests.
    if not include_extra and os.getenv('LEXBET_EXTRA_MARKETS','0') != '1':
        event_sources=[]
    for sport,event in event_sources[:8]:
        if event not in today_events: continue
        event_id=event.get('id')
        if not event_id: continue
        try:
            query=urlencode({'apiKey':key,'regions':'uk,eu','markets':'btts,draw_no_bet,double_chance,spreads','oddsFormat':'decimal'})
            req=Request(f'https://api.the-odds-api.com/v4/sports/{sport}/events/{event_id}/odds?{query}', headers={'User-Agent':'lexbet-chat/1.0'})
            with urlopen(req, timeout=8) as response: extra=json.loads(response.read())
        except Exception:
            continue
        groups={}
        for book in extra.get('bookmakers',[]):
            for market_data in book.get('markets',[]):
                mk=market_data.get('key')
                if mk not in {'btts','draw_no_bet','double_chance','spreads'}: continue
                for outcome in market_data.get('outcomes',[]):
                    name=outcome.get('name'); price=outcome.get('price'); point=outcome.get('point')
                    if name and price: groups.setdefault((mk,str(point) if point is not None else '',name),[]).append(float(price))
        home=event.get('home_team','Home'); away=event.get('away_team','Away')
        for (mk,point,name), values in groups.items():
            siblings=[(n,v) for (m,p,n),v in groups.items() if m==mk and p==point]
            if len(siblings)<2: continue
            avg={n:sum(v)/len(v) for n,v in siblings}; inv={n:1/p for n,p in avg.items()}; total=sum(inv.values())
            prob=inv[name]/total; display=name if point=='' else f'{name} {point}'
            market={'btts':'BTTS','draw_no_bet':'DNB','double_chance':'DOUBLE_CHANCE','spreads':'HANDICAP'}[mk]
            out.append({'home_team':home,'away_team':away,'market':market,'selection':name,'display_selection':display,'odds':avg[name],'model_prob':prob,'market_prob':prob,'blended_prob':prob,'confidence':'Market consensus','rationale':f"Today's bookmaker consensus is {prob:.1%} for {display}. This is a live market-only candidate from the requested match-market feed.",'risks':'This market is not a guarantee; verify lineups, motivation, and the exact handicap or settlement rule.','alternatives':f"Compare the other {market} outcomes before staking; a shorter price is not automatically safer."})
    # Keep the desk genuinely mixed: prefer one candidate from each available
    # market family, then fill from the remaining highest-likelihood candidates.
    ranked=sorted(out, key=lambda x:x['blended_prob'], reverse=True)
    selected=[]
    for market_name in ('1X2','OU25','BTTS','DNB','DOUBLE_CHANCE','HANDICAP'):
        candidate=next((x for x in ranked if x['market']==market_name), None)
        if candidate: selected.append(candidate)
        if len(selected)>=5: break
    selected=sorted(selected, key=lambda x:x['blended_prob'], reverse=True)
    seen={(x['home_team'],x['away_team'],x['market'],x['selection']) for x in selected}
    for item in ranked:
        keyset=(item['home_team'],item['away_team'],item['market'],item['selection'])
        if keyset not in seen:
            selected.append(item); seen.add(keyset)
        if len(selected) >= 50: break
    return selected

def _number(text):
    m=re.search(r'\b([1-9]|[1-4][0-9])\b', text)
    return int(m.group(1)) if m else 5

def _gemini_reply(message, picks, history):
    """Optionally turn the grounded live-pick context into a natural chat reply."""
    key=os.getenv('GEMINI_API_KEY')
    if not key: return None
    context=json.dumps([{k:p.get(k) for k in ('home_team','away_team','market','display_selection','odds','blended_prob','rationale','risks')} for p in picks], ensure_ascii=False) if picks else 'No live candidates are currently available.'
    transcript='\n'.join(f"{x.get('role','user')}: {x.get('content','')}" for x in history[-12:] if isinstance(x,dict))
    prompt=("You are Lexbet, a natural conversational football betting analyst. Continue the conversation instead of repeating a canned instruction. "
            "Answer casual messages naturally, answer follow-up questions directly, and compare or challenge picks when asked. Use only the live fixture and market context below. "
            "Do not invent injuries, form, fixtures, odds, or statistics. Explain that likelihood is not certainty, avoid promising wins, and keep the answer under 120 words. "
            f"\nLive context: {context}\nConversation:\n{transcript}\nLatest user message: {message}")
    body=json.dumps({'contents':[{'parts':[{'text':prompt}]}], 'generationConfig':{'temperature':0.2,'maxOutputTokens':220}}).encode()
    try:
        req=Request('https://generativelanguage.googleapis.com/v1beta/interactions', data=json.dumps({'model':'gemini-4-argon','input':prompt}).encode(), headers={'Content-Type':'application/json','x-goog-api-key':key,'User-Agent':'lexbet-chat/1.0'})
        with urlopen(req, timeout=10) as response:
            data=json.loads(response.read())
        if data.get('output_text'): return data['output_text'].strip()
        for item in data.get('outputs',[]):
            if item.get('text'): return item['text'].strip()
    except Exception:
        pass
    # Compatibility path for keys/models that have not been enabled for Interactions.
    body=json.dumps({'contents':[{'parts':[{'text':prompt}]}], 'generationConfig':{'temperature':0.2,'maxOutputTokens':220}}).encode()
    for model in ('gemini-3.5-flash-lite','gemini-2.5-flash'):
        try:
            req=Request(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent', data=body, headers={'Content-Type':'application/json','x-goog-api-key':key,'User-Agent':'lexbet-chat/1.0'})
            with urlopen(req, timeout=10) as response: data=json.loads(response.read())
            return data['candidates'][0]['content']['parts'][0]['text'].strip()
        except Exception:
            continue
    return None

def answer(message, history=None):
    text=message.lower()
    wants_btts=any(term in text for term in ('btts','both teams to score','gg/ng','gg ng','both sides score'))
    wants_double_chance=any(term in text for term in ('double chance','1x','x2','12'))
    rows=_rows(include_extra=wants_btts or wants_double_chance)
    n=_number(text)
    history=history or []
    if not rows:
        # Do not send an empty market context to Gemini: it may reinterpret
        # phrases such as "10 odds" as an accumulator and invent advice.
        return {'reply':f"I can’t see today’s live odds right now, so I can’t give you {n} picks or build an accumulator without inventing fixtures and prices. Try again when the live feed is available, or ask me about a market such as BTTS or Double Chance.", 'picks':[], 'count':0}
    wants_picks=any(word in text for word in ['best','safest','odds','today','picks','recommend','show me'])
    preferred_market='BTTS' if wants_btts else 'DOUBLE_CHANCE' if wants_double_chance else None
    mentioned=[r for r in rows if r['home_team'].lower() in text or r['away_team'].lower() in text]
    ordered=([r for r in rows if r['market']==preferred_market] if preferred_market else []) + [r for r in rows if r['market']!=preferred_market]
    ordered_mentioned=[r for r in ordered if r['home_team'].lower() in text or r['away_team'].lower() in text]
    ordered_others=[r for r in ordered if r not in ordered_mentioned]
    contextual=(ordered_mentioned + ordered_others)[:n] if wants_picks else ((ordered_mentioned + ordered_others)[:8])
    ai_reply=_gemini_reply(message, contextual, history)
    if ai_reply:
        return {'reply':ai_reply, 'picks':contextual if wants_picks else [], 'count':len(rows)}
    if any(word in text for word in ['best','safest','odds','today','picks','recommend']):
        picks=rows[:n]
        reply=_gemini_reply(message, picks, history) or f"Here are today's {len(picks)} strongest mixed-market outcomes. I ranked them by estimated likelihood, not by edge. Challenge the risk note on each one."
        return {'reply':reply, 'picks':picks, 'count':len(picks)}
    match=next((r for r in rows if r['home_team'].lower() in text or r['away_team'].lower() in text), None)
    if match:
        return {'reply':f"Here is the case for {match['home_team']} v {match['away_team']}. Ask me to challenge any part of it.", 'picks':[match], 'count':1}
    if 'why' in text or 'risk' in text or 'debate' in text:
        return {'reply':'Tell me which part of the call you want to challenge. I can explain the evidence, compare the alternatives, or show what would make me change the recommendation.', 'picks':rows[:3], 'count':min(3,len(rows))}
    if any(word in text for word in ['hi','hello','hey','what’s up',"what's up",'how are you']):
        return {'reply':'I’m here and watching today’s fixtures. Ask me for the best picks, challenge one of the calls, or name a match and I’ll compare the available markets.', 'picks':[], 'count':len(rows)}
    return {'reply':'Tell me which match or pick you want to examine. I can compare the result, totals, BTTS, double chance, draw-no-bet, and handicap markets where live odds are available.', 'picks':[], 'count':len(rows)}

def handle_request(request):
    if request.method != 'POST':
        return {'statusCode':405,'headers':{'Content-Type':'application/json'},'body':json.dumps({'error':'POST a JSON message'})}
    try: payload=json.loads(request.body or '{}')
    except Exception: payload={}
    result=answer(str(payload.get('message','')), payload.get('history') or [])
    return {'statusCode':200,'headers':{'Content-Type':'application/json','Cache-Control':'no-store'},'body':json.dumps(result)}

async def app(scope, receive, send):
    """Minimal ASGI entrypoint supported by Vercel's Python runtime."""
    body = b''
    while True:
        event = await receive()
        body += event.get('body', b'')
        if not event.get('more_body'):
            break
    request = type('Request', (), {
        'method': scope.get('method', 'GET'),
        'body': body,
    })()
    result = handle_request(request)
    payload = result['body'].encode()
    headers = [(key.encode(), value.encode()) for key, value in result.get('headers', {}).items()]
    headers.append((b'content-length', str(len(payload)).encode()))
    await send({'type': 'http.response.start', 'status': result['statusCode'], 'headers': headers})
    await send({'type': 'http.response.body', 'body': payload})
