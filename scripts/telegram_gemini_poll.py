#!/usr/bin/env python3
from __future__ import annotations
import json, os
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/'reports/backtest.json'

def tg(token, method, payload):
    r=requests.post(f'https://api.telegram.org/bot{token}/{method}',json=payload,timeout=40); r.raise_for_status(); return r.json()

def gemini(key, question, context):
    prompt=("You are Lexbet's cautious football-betting analyst. Discuss probabilities and uncertainty, never claim a pick is guaranteed, never encourage chasing losses, and say no bet when evidence is weak. "
            "Use only the supplied context; do not invent injuries, odds, fixtures, or statistics. Explain that the system is paper-trading only.\n\n"
            f"Backtest context:\n{context}\n\nUser question:\n{question}")
    body={'contents':[{'parts':[{'text':prompt}]}],'generationConfig':{'temperature':.2,'maxOutputTokens':500}}
    last=None
    for model in ('gemini-2.5-flash','gemini-2.5-flash-lite','gemini-3.5-flash-lite','gemini-3.1-flash-lite'):
        url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        r=requests.post(url,params={'key':key},json=body,timeout=45)
        if r.status_code == 404: last=r; continue
        r.raise_for_status(); data=r.json(); return data['candidates'][0]['content']['parts'][0]['text']
    if last is not None: last.raise_for_status()
    raise RuntimeError('No Gemini model endpoint was available')

def main():
    token=os.getenv('TELEGRAM_BOT_TOKEN'); key=os.getenv('GEMINI_API_KEY'); chat_id=os.getenv('TELEGRAM_CHAT_ID')
    if not token or not key or not chat_id:
        print('Chat skipped: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, and GEMINI_API_KEY are required.'); return
    # offset=-1 asks Telegram for the newest unconfirmed update and confirms older backlog.
    updates=tg(token,'getUpdates',{'offset':-1,'limit':1,'timeout':1,'allowed_updates':['message']}).get('result',[])
    if not updates: print('No new Telegram messages.'); return
    update=updates[-1]; msg=update.get('message',{}); text=(msg.get('text') or '').strip(); incoming=str(msg.get('chat',{}).get('id'))
    if not text or incoming != str(chat_id) or msg.get('from',{}).get('is_bot'): return
    context=REPORT.read_text() if REPORT.exists() else 'No backtest report is available.'
    try: answer=gemini(key,text,context)
    except requests.HTTPError as exc:
        code=exc.response.status_code if exc.response is not None else 'unknown'
        answer=f"Gemini rejected the request (HTTP {code}). Check that GEMINI_API_KEY is a Google AI Studio key with Gemini API access. No pick should be treated as guaranteed."
    except Exception as exc: answer=f"I could not reach Gemini right now. No pick should be treated as guaranteed. Technical detail: {type(exc).__name__}."
    tg(token,'sendMessage',{'chat_id':chat_id,'text':answer[:3900]})
    # Confirm this update without needing a persistent server-side offset file.
    tg(token,'getUpdates',{'offset':int(update['update_id'])+1,'limit':1,'timeout':1,'allowed_updates':['message']})
    print('Answered one Telegram message with Gemini.')
if __name__=='__main__': main()
