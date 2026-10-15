import json
import os
import csv
from datetime import datetime
import time
import yfinance as yf
from google import genai
from google.genai import types

DATA_DIR = "trading_agent_data"
PROMPTS_DIR = "prompts"

# Liste élargie de 12 titres (Canadiens .TO et Géants US) analysés à chaque requête
WATCHLIST = [
    "VFV.TO", "XEQT.TO", "SHOP.TO", "CSU.TO", 
    "RY.TO", "TD.TO", "ATD.TO", "DOL.TO", 
    "AAPL", "MSFT", "NVDA", "TSLA"
]

# Configuration des 5 Bots
BOTS = {
    "momentum": {"name": "🔥 Trend Follower (Momentum)", "prompt_file": "momentum.txt"},
    "value": {"name": "🏛️ Value Compounder (Buffett)", "prompt_file": "value.txt"},
    "quant": {"name": "⚡ Mean Reverter (Quant)", "prompt_file": "quant.txt"},
    "growth": {"name": "🚀 Growth Breakout (Tech)", "prompt_file": "growth.txt"},
    "macro": {"name": "🌍 Macro Sentiment (Dalio)", "prompt_file": "macro.txt"}
}

def ensure_dirs():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def get_files(bot_id):
    return {
        "portfolio": os.path.join(DATA_DIR, f"portfolio_{bot_id}.json"),
        "trades": os.path.join(DATA_DIR, f"trades_{bot_id}.csv"),
        "logs": os.path.join(DATA_DIR, f"logs_{bot_id}.json")
    }

def load_portfolio(bot_id):
    ensure_dirs()
    filepath = get_files(bot_id)["portfolio"]
    if not os.path.exists(filepath):
        initial_state = {
            "cash_cad": 1000.0,
            "positions": {},
            "history_valuation": []
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(initial_state, f, indent=2)
        return initial_state
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

def save_portfolio(bot_id, data):
    filepath = get_files(bot_id)["portfolio"]
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def log_trade(bot_id, date, ticker, action, shares, price, fx_rate, fee_cad, cash_left, reason):
    filepath = get_files(bot_id)["trades"]
    file_exists = os.path.isfile(filepath)
    with open(filepath, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Date", "Ticker", "Action", "Shares", "Price", "FX_Rate", "Fee_CAD", "Cash_CAD_Left", "Reason"])
        writer.writerow([date, ticker, action, round(shares, 4), round(price, 2), round(fx_rate, 4), round(fee_cad, 2), round(cash_left, 2), reason])

def log_ai_request(bot_id, date, model_used, market_snapshot, decision, order_executed):
    """Enregistre TOUTES les réflexions de l'IA (même les HOLD) pour pouvoir les lire sur le Dashboard."""
    filepath = get_files(bot_id)["logs"]
    logs = []
    if os.path.exists(filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                logs = json.load(f)
        except Exception:
            logs = []

    log_entry = {
        "date": date,
        "model": model_used,
        "tickers_analyzed_count": len(market_snapshot),
        "tickers_analyzed": list(market_snapshot.keys()),
        "action": decision.get("action", "HOLD"),
        "ticker": decision.get("ticker", "AUCUN"),
        "amount_cad": decision.get("amount_cad", 0.0),
        "order_executed": order_executed,
        "experts": decision.get("experts", {}),
        "synthese": decision.get("synthese", ""),
        "reasoning": decision.get("reasoning", "")
    }

    logs.append(log_entry)
    # On garde les 100 dernières requêtes pour garder un fichier léger
    logs = logs[-100:]

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(logs, f, indent=2, ensure_ascii=False)

def fetch_all_market_data(watchlist):
    """Récupère les données du marché une seule fois pour tous les bots."""
    fx = yf.Ticker("CADUSD=X").history(period="5d")
    cad_to_usd = fx["Close"].iloc[-1] if not fx.empty else 0.73
    usd_to_cad = 1.0 / cad_to_usd

    market_data = {}
    for ticker in watchlist:
        try:
            stock = yf.Ticker(ticker)
            history = stock.history(period="1mo")
            if not history.empty:
                closes = [round(x, 2) for x in history["Close"].tail(5).tolist()]
                change_5d_pct = round(((closes[-1] - closes[0]) / closes[0]) * 100, 2) if len(closes) > 1 else 0.0
                market_data[ticker] = {
                    "price": float(history["Close"].iloc[-1]),
                    "is_us": not ticker.endswith(".TO"),
                    "usd_to_cad": float(usd_to_cad),
                    "history_close": closes,
                    "variation_5j_pct": f"{change_5d_pct}%"
                }
        except Exception as e:
            print(f"Erreur téléchargement pour {ticker}: {e}")
    return market_data

def read_strategy_prompt(filename):
    filepath = os.path.join(PROMPTS_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    else:
        print(f"ATTENTION: Fichier {filepath} introuvable. Utilisation d'un prompt par défaut.")
        return "Tu es un gestionnaire de portefeuille prudent opérant sur Wealthsimple."

def execute_order(bot_id, portfolio, ticker, action, amount_cad, reason, market_data, today):
    data = market_data.get(ticker)
    if not data:
        return False

    price = data["price"]
    is_us = data["is_us"]
    usd_to_cad = data["usd_to_cad"]
    fx_fee_rate = 0.015 if is_us else 0.0

    if action == "BUY":
        if amount_cad <= 0 or amount_cad > portfolio["cash_cad"]:
            print(f"[{bot_id}] Fonds insuffisants ou montant invalide ({amount_cad}$ demandé, {portfolio['cash_cad']:.2f}$ dispo).")
            return False

        fee_cad = amount_cad * fx_fee_rate
        net_invest_cad = amount_cad - fee_cad
        shares = (net_invest_cad / usd_to_cad) / price if is_us else net_invest_cad / price

        portfolio["cash_cad"] -= amount_cad
        pos = portfolio["positions"].get(ticker, {"shares": 0.0, "total_cost_cad": 0.0})
        pos["shares"] += shares
        pos["total_cost_cad"] += amount_cad
        pos["avg_price_cad"] = pos["total_cost_cad"] / pos["shares"]
        portfolio["positions"][ticker] = pos

        log_trade(bot_id, today, ticker, "BUY", shares, price, usd_to_cad if is_us else 1.0, fee_cad, portfolio["cash_cad"], reason)
        return True

    elif action == "SELL":
        pos = portfolio["positions"].get(ticker)
        if not pos or pos["shares"] <= 0:
            return False

        shares = pos["shares"]
        gross_cad = (shares * price) * usd_to_cad if is_us else shares * price
        fee_cad = gross_cad * fx_fee_rate
        net_cad = gross_cad - fee_cad

        portfolio["cash_cad"] += net_cad
        del portfolio["positions"][ticker]

        log_trade(bot_id, today, ticker, "SELL", shares, price, usd_to_cad if is_us else 1.0, fee_cad, portfolio["cash_cad"], reason)
        return True
    return False

def ask_trading_brain(bot_id, portfolio, market_snapshot, strategy_text):
    client = genai.Client()

    prompt = f"""
    === INSTRUCTIONS DE STRATÉGIE SPÉCIFIQUE ===
    {strategy_text}

    === ÉTAT ACTUEL DE TON PORTEFEUILLE (Compte Canadien CAD) ===
    - Capital initial : 1000.00 $ CAD
    - Liquidités disponibles (Cash) : {portfolio['cash_cad']:.2f} $ CAD
    - Positions actuellement en portefeuille : {json.dumps(portfolio['positions'], indent=2)}

    === DONNÉES DU MARCHÉ ({len(market_snapshot)} TITRES ANALYSÉS AUJOURD'HUI) ===
    {json.dumps(market_snapshot, indent=2)}

    === PROCESSUS DE DÉLIBÉRATION OBLIGATOIRE ===
    Avant de trancher, fais débattre tes 3 experts (L'Opérateur, Le Sceptique, Le Visionnaire).
    Le Sceptique DOIT jouer l'avocat du diable et souligner les dangers ou les frais.
    Explique clairement dans ton raisonnement pourquoi tu choisis d'agir (BUY/SELL) ou pourquoi aucun des {len(market_snapshot)} titres ne mérite d'action aujourd'hui (HOLD).

    Réponds EXCLUSIVEMENT avec un objet JSON valide suivant exactement cette structure :
    {{
      "experts": {{
        "operateur": "Avis détaillé de l'Opérateur sur l'exécution, les liquidités et les frais...",
        "sceptique": "Avis critique du Sceptique (avocat du diable) sur les risques et les positions...",
        "visionnaire": "Avis du Visionnaire sur les opportunités parmi les titres analysés..."
      }},
      "synthese": "Synthèse du débat du comité en 2-3 phrases...",
      "action": "BUY" | "SELL" | "HOLD",
      "ticker": "SYMBOLE_CHOISI_OU_AUCUN",
      "amount_cad": 250.0,
      "reasoning": "Explication complète et transparente de la décision finale."
    }}
    """

    models_to_try = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash-lite", "gemini-2.5-flash"]
    for model_name in models_to_try:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                return json.loads(response.text), model_name
            except Exception as e:
                print(f"[{bot_id}] Essai échoué sur {model_name} (tentative {attempt+1}): {e}")
                time.sleep(4)

    return {
        "experts": {
            "operateur": "API indisponible.",
            "sceptique": "API indisponible.",
            "visionnaire": "API indisponible."
        },
        "synthese": "Impossible de joindre les modèles Gemini lors de cette exécution.",
        "action": "HOLD",
        "ticker": "AUCUN",
        "amount_cad": 0.0,
        "reasoning": "Mise en attente automatique suite à une surcharge de l'API."
    }, "erreur-api"

def run_arena():
    print("Téléchargement des données du marché...")
    raw_market_data = fetch_all_market_data(WATCHLIST)
    
    # Préparation du résumé propre envoyé aux IA
    market_snapshot = {}
    for sym, d in raw_market_data.items():
        market_snapshot[sym] = {
            "prix_actuel": round(d["price"], 2),
            "devise_et_marche": "USD (Frais FX 1.5%)" if d["is_us"] else "CAD (0% Frais)",
            "historique_5j": d["history_close"],
            "variation_5j": d["variation_5j_pct"]
        }

    today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for index, (bot_id, bot_info) in enumerate(BOTS.items()):
        print(f"\n--- Exécution de {bot_info['name']} ---")
        portfolio = load_portfolio(bot_id)
        strategy_text = read_strategy_prompt(bot_info["prompt_file"])

        decision, model_used = ask_trading_brain(bot_id, portfolio, market_snapshot, strategy_text)
        print(f"[{bot_id}] Décision ({model_used}) : {decision.get('action')} sur {decision.get('ticker')}")

        order_executed = False
        action = decision.get("action", "HOLD")
        ticker = decision.get("ticker", "AUCUN")

        if action in ["BUY", "SELL"] and ticker in raw_market_data:
            order_executed = execute_order(
                bot_id=bot_id,
                portfolio=portfolio,
                ticker=ticker,
                action=action,
                amount_cad=float(decision.get("amount_cad", 0)),
                reason=decision.get("reasoning", ""),
                market_data=raw_market_data,
                today=today
            )

        # Enregistrement systématique dans le journal des requêtes (même si HOLD)
        log_ai_request(bot_id, today, model_used, market_snapshot, decision, order_executed)

        # Calcul de la valeur totale du portefeuille du bot
        total_val_cad = portfolio["cash_cad"]
        for sym, pos in portfolio["positions"].items():
            d = raw_market_data.get(sym)
            if d:
                if d["is_us"]:
                    total_val_cad += (pos["shares"] * d["price"]) * d["usd_to_cad"]
                else:
                    total_val_cad += pos["shares"] * d["price"]

        portfolio["history_valuation"].append({
            "date": today,
            "total_value_cad": round(total_val_cad, 2)
        })
        save_portfolio(bot_id, portfolio)

        # Pause de 15 secondes entre chaque bot pour respecter la limite de 5 RPM de Gemini
        if index < len(BOTS) - 1:
            time.sleep(15)

if __name__ == "__main__":
    run_arena()
