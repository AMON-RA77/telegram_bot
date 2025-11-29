import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import yfinance as yf
import pandas as pd
import datetime

# ---------- Variables globales ----------
active_chats = set()
user_waiting_for_capital = set()
capital = 0.0
analyse_sans_signal = 0

# Symboles : indices, crypto, forex
symbols = {
    "SP500": "^GSPC",
    "NASDAQ": "^IXIC",
    "DJIA": "^DJI",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
    "EURUSD": "EURUSD=X",
    "USDJPY": "JPY=X"
}

timeframes = ["1m", "5m", "15m", "1h", "4h"]

RISK_PERCENT = 0.02  # 2% du capital par trade

# ---------- Handlers Telegram ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_chat.id
    active_chats.add(user_id)
    user_waiting_for_capital.add(user_id)
    await update.message.reply_text(
        "Salut mon samouraï ! Donne‑moi ton capital en € (écris juste le nombre) :"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global capital
    user_id = update.effective_chat.id
    if user_id in user_waiting_for_capital:
        try:
            val = float(update.message.text.replace("€","").strip())
            capital = val
            user_waiting_for_capital.remove(user_id)
            await update.message.reply_text(f"Parfait, j'ai bien reçu ton capital : {capital} €")
        except:
            await update.message.reply_text("Erreur — écris juste un nombre pour ton capital.")
    else:
        await update.message.reply_text("Tu peux envoyer /signal ou attendre les signaux automatiques.")

# ---------- Analyse des marchés ----------
def analyze_data(df: pd.DataFrame):
    last = df.iloc[-1]
    sma20 = df["Close"].rolling(window=20).mean().iloc[-1] if len(df)>=20 else None
    vol_avg = df["Volume"].rolling(window=20).mean().iloc[-1] if len(df)>=20 else None

    buy_score = 0
    checks = 0

    if last["Close"] > last["Open"]:
        buy_score += 1
    checks += 1

    if vol_avg is not None and last["Volume"] > vol_avg:
        buy_score += 1
    checks += 1

    if sma20 is not None and last["Close"] > sma20:
        buy_score += 1
    checks += 1

    confidence = buy_score / checks if checks>0 else 0
    signal = "BUY" if confidence > 0 else None  # envoie tout signal même faible
    return signal, confidence, last["Close"]

def calculate_tp_sl(price, signal_type):
    # Exemple simple : TP = +2%, SL = -2%
    if signal_type == "BUY":
        tp = price * 1.02
        sl = price * 0.98
    else:
        tp = price * 0.98
        sl = price * 1.02
    return round(tp,5), round(sl,5)

async def analyze_markets(context: ContextTypes.DEFAULT_TYPE):
    global analyse_sans_signal

    now = datetime.datetime.utcnow()
    if now.hour >= 22:
        return
    if not active_chats or capital <= 0:
        return

    results = []
    for name, ticker in symbols.items():
        for tf in timeframes:
            try:
                df = yf.download(ticker, period="5d", interval=tf, progress=False)
                if df.empty or len(df)<5:
                    continue
                sig, conf, price = analyze_data(df)
                if sig:
                    tp, sl = calculate_tp_sl(price, sig)
                    size = round(capital * RISK_PERCENT, 2)
                    results.append((name, tf, sig, conf, price, tp, sl, size))
            except:
                continue

    for chat_id in active_chats:
        if results:
            analyse_sans_signal = 0
            for name, tf, sig, conf, price, tp, sl, size in results:
                msg = (f"📊 Marché : {name}\n"
                       f"⏱ Timeframe : {tf}\n"
                       f"📈 Signal : {sig}\n"
                       f"🎯 Confiance : {conf*100:.1f}%\n"
                       f"Prix actuel : {price}\n"
                       f"TP : {tp}\n"
                       f"SL : {sl}\n"
                       f"Taille position : {size} €")
                await context.bot.send_message(chat_id=chat_id, text=msg)
        else:
            analyse_sans_signal += 1
            if analyse_sans_signal >= 10:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="🕒 10 recherches terminées, aucun signal trouvé.\nPatiente, mon Samouraï."
                )
                analyse_sans_signal = 0

# ---------- Commande /signal ----------
async def signal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if capital <= 0:
        await update.message.reply_text("Donne d'abord ton capital avec /start !")
        return
    await analyze_markets(context)
    await update.message.reply_text("Analyse immédiate terminée — vérifie tes messages !")

# ---------- Setup du bot ----------
TOKEN = "8332087651:AAGYcP9WHL9NNWcJK4MFuyEXLcfiOsDmHoI"

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("signal", signal_command))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

job = app.job_queue
job.run_repeating(analyze_markets, interval=60, first=10)
app.run_polling()
