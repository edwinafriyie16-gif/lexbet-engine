from __future__ import annotations
import json, os, sqlite3
from pathlib import Path


def format_picks(picks: list[dict]) -> str:
    if not picks: return "No likely-result recommendations met the confidence threshold. No bet is still a valid outcome."
    lines=["Lexbet likely-result recommendations", "These are probability-based opinions, not guarantees or financial advice. Debate the evidence before staking."]
    for p in picks:
        lines.append(
            f"\n{p['home_team']} v {p['away_team']} — {p['selection']} @ {p['odds']:.2f}\n"
            f"Likelihood: {p['blended_prob']:.1%} | Confidence: {p.get('confidence', 'Unknown')}\n"
            f"Why: {p.get('rationale', 'No rationale stored.')}\n"
            f"Risks: {p.get('risks', 'No risk notes stored.')}\n"
            f"Debate: {p.get('alternatives', 'Challenge the assumptions and check team news before staking.')}")
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
