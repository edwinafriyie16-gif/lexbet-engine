from __future__ import annotations
import os


def format_picks(picks: list[dict]) -> str:
    if not picks: return "No qualifying picks. No bet is a valid outcome."
    lines = ["Lexbet value-betting research picks", "Not guaranteed. Stake only what you can afford to lose."]
    for p in picks:
        lines.append(f"{p['home_team']} v {p['away_team']} — {p['market']} @ {p['odds']:.2f}; blended p={p['prob']:.1%}; edge={p['edge']:.1%}; stake={p['stake']:.2%} bankroll")
    return "\n".join(lines)


def build_application(engine):
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    app = Application.builder().token(token).build()
    async def picks(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(format_picks(engine.picks()))
    async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(str(engine.stats()))
    async def bankroll(update: Update, context: ContextTypes.DEFAULT_TYPE): await update.message.reply_text(f"Bankroll: {engine.bankroll:.2f}. Max stake per bet: 2%.")
    app.add_handler(CommandHandler("picks", picks)); app.add_handler(CommandHandler("stats", stats)); app.add_handler(CommandHandler("bankroll", bankroll))
    return app
