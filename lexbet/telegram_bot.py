from __future__ import annotations
import json, os, sqlite3
from pathlib import Path


def format_picks(picks: list[dict]) -> str:
    if not picks: return "No qualifying picks. No bet is a valid outcome."
    lines=["Lexbet value-betting research picks", "Not guaranteed. Paper-trading only; stake only what you can afford to lose."]
    for p in picks:
        lines.append(f"{p['home_team']} v {p['away_team']} — {p['market']} {p['selection']} @ {p['odds']:.2f}; blended p={p['blended_prob']:.1%}; edge={p['edge']:.1%}; stake={p['stake']:.2f}")
    return "\n".join(lines)

class SQLiteEngine:
    def __init__(self, db_path=None, bankroll=None):
        self.db_path=db_path or os.getenv('LEXBET_DB_PATH','data/lexbet.sqlite'); self.bankroll=float(bankroll or os.getenv('LEXBET_BANKROLL','1000'))
    def _conn(self): return sqlite3.connect(self.db_path)
    def picks(self):
        c=self._conn(); c.row_factory=sqlite3.Row; rows=c.execute("select * from picks where status='open' and kickoff > datetime('now') order by kickoff").fetchall(); c.close(); return [dict(x) for x in rows]
    def stats(self):
        c=self._conn(); c.row_factory=sqlite3.Row
        run=c.execute('select metrics_json from backtest_runs order by created_at desc limit 1').fetchone(); paper=c.execute("select count(*) n, coalesce(sum(profit),0) profit, coalesce(avg(profit),0) avg_profit from paper_trades where settled_at is not null").fetchone(); c.close()
        return {'backtest': json.loads(run['metrics_json']) if run else None, 'paper_trade': dict(paper) if paper else {'n':0,'profit':0,'avg_profit':0}}

def build_application(engine=None):
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    token=os.environ['TELEGRAM_BOT_TOKEN']; engine=engine or SQLiteEngine(); app=Application.builder().token(token).build()
    async def picks(update:Update, context:ContextTypes.DEFAULT_TYPE): await update.message.reply_text(format_picks(engine.picks()))
    async def stats(update:Update, context:ContextTypes.DEFAULT_TYPE): await update.message.reply_text(json.dumps(engine.stats(),indent=2,default=str))
    async def bankroll(update:Update, context:ContextTypes.DEFAULT_TYPE): await update.message.reply_text(f"Paper bankroll: {engine.bankroll:.2f}. Maximum stake per bet: 2%. No result is guaranteed.")
    app.add_handler(CommandHandler('picks',picks)); app.add_handler(CommandHandler('stats',stats)); app.add_handler(CommandHandler('bankroll',bankroll)); return app
