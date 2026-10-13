import json
import os
import csv
from datetime import datetime
import time
import yfinance as yf
from google import genai
from google.genai import types

DATA_DIR = "trading_agent_data"
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")
LOG_FILE = os.path.join(DATA_DIR, "trades.csv")

def load_portfolio():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    if not os.path.exists(PORTFOLIO_FILE):
        initial_state = {
            "cash_cad": 1000.0,
            "positions": {},
            "history_valuation": []
        }
        with open(PORTFOLIO_FILE, "w") as f:
            json.dump(initial_state, f, indent=2)
        return initial_state
    with open(PORTFOLIO_FILE, "r") as f:
        return json.load(f)

def save_portfolio(data):
    with open(PORTFOLIO_FILE, "w") as f:
        json.dump(data, f, indent=2)

def log_trade(date, ticker, action, shares, price, fx_rate, fee_cad, cash_left, reason):
    file_exists = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, mode="a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Date", "Ticker", "Action", "Shares", "Price", "FX_Rate", "Fee_CAD", "Cash_CAD_Left", "Reason"])
        writer.writerow([date, ticker, action, round(shares, 4), round(price, 2), round(fx_rate, 4), round(fee_cad, 2), round(cash_left, 2), reason])

def get_market_data(ticker):
    stock = yf.Ticker(ticker)
    history = stock.history(period="1mo")
    if history.empty:
        return None
    current_price = history["Close"].iloc[-1]
    
    fx = yf.Ticker("CADUSD=X").history(period="1d")
    cad_to_usd = fx["Close"].iloc[-1]
    usd_to_cad = 1.0 / cad_to_usd
    
    return {
        "price": current_price,
        "is_us": not ticker.endswith(".TO"),
        "usd_to_cad": usd_to_cad,
        "history_close": history["Close"].tail(5).tolist()
    }

def execute_order(portfolio, ticker, action, amount_cad, reason):
    data = get_market_data(ticker)
    if not data:
        print(f"Erreur données marché pour {ticker}")
        return False

    price = data["price"]
    is_us = data["is_us"]
    usd_to_cad = data["usd_to_cad"]
    fx_fee_rate = 0.015 if is_us else 0.0
    today = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if action == "BUY":
        if amount_cad > portfolio["cash_cad"]:
            print(f"Fonds insuffisants : {amount_cad}$ demandé, {portfolio['cash_cad']}$ dispo.")
            return False

        fee_cad = amount_cad * fx_fee_rate
        net_invest_cad = amount_cad - fee_cad

        if is_us:
            invest_usd = net_invest_cad / usd_to_cad
            shares = invest_usd / price
        else:
            shares = net_invest_cad / price

        portfolio["cash_cad"] -= amount_cad
        pos = portfolio["positions"].get(ticker, {"shares": 0.0, "total_cost_cad": 0.0})
        pos["shares"] += shares
        pos["total_cost_cad"] += amount_cad
        pos["avg_price_cad"] = pos["total_cost_cad"] / pos["shares"]
        portfolio["positions"][ticker] = pos

        log_trade(today, ticker, "BUY", shares, price, usd_to_cad if is_us else 1.0, fee_cad, portfolio["cash_cad"], reason)
        print(f"Achat exécuté : {shares:.4f} actions de {ticker} (Frais: {fee_cad:.2f}$ CAD)")
        return True

    elif action == "SELL":
        pos = portfolio["positions"].get(ticker)
        if not pos or pos["shares"] <= 0:
            print(f"Position inexistante pour {ticker}")
            return False

        shares = pos["shares"]
        if is_us:
            gross_cad = (shares * price) * usd_to_cad
        else:
            gross_cad = shares * price

        fee_cad = gross_cad * fx_fee_rate
        net_cad = gross_cad - fee_cad

        portfolio["cash_cad"] += net_cad
        del portfolio["positions"][ticker]

        log_trade(today, ticker, "SELL", shares, price, usd_to_cad if is_us else 1.0, fee_cad, portfolio["cash_cad"], reason)
        print(f"Vente exécutée : {ticker} (Gain net: {net_cad:.2f}$, Frais: {fee_cad:.2f}$ CAD)")
        return True

def ask_trading_brain(portfolio, watchlist):
    client = genai.Client()
    market_snapshot = {}
    for ticker in watchlist:
        d = get_market_data(ticker)
        if d:
            market_snapshot[ticker] = {
                "dernier_prix": round(d["price"], 2),
                "marche": "US" if d["is_us"] else "TSX",
                "historique_5j": [round(x, 2) for x in d["history_close"]]
            }

    prompt = f"""
    Tu es un gestionnaire de portefeuille automatisé opérant sur Wealthsimple avec un compte canadien (CAD).
    Capital initial : 1000 $ CAD.
    État actuel :
    - Liquidités disponibles : {portfolio['cash_cad']:.2f} $ CAD
    - Positions ouvertes : {portfolio['positions']}
    
    Données de marché récentes :
    {json.dumps(market_snapshot, indent=2)}

    Règles strictes :
    1. Frais de 1,5% à l'achat et 1,5% à la vente sur les actions US (soit 3% aller-retour). Privilégie le marché canadien (.TO) sauf si opportunité US majeure.
    2. Fréquence : Tu agis 1 à 2 fois par semaine maximum. Si le marché est incertain, choisis HOLD.
    3. Gestion des risques : Ne risque pas plus de 30% du capital sur un seul titre.

    AVANT de prendre ta décision, tu dois réunir un comité virtuel d'experts pour analyser la situation.
    Analyse les actifs de la liste de surveillance selon les 3 perspectives suivantes :
    
    1. L'Opérateur (Exécution) : Analyse la faisabilité technique, les frais (surtout les 3% FX pour les actions US) et la liquidité. Est-ce pertinent d'exécuter un trade maintenant ?
    2. Le Sceptique (Risque) : Analyse les risques de baisse, la volatilité récente (historique_5j) et la concentration (règle des 30%). Quels sont les dangers ?
    3. Le Visionnaire (Occasion) : Analyse le potentiel de croissance à court terme. Pourquoi est-ce une opportunité à saisir ?

    Réponds EXCLUSIVEMENT avec un JSON au format exact suivant (aucun texte avant ou après) :
    {{
      "experts": {{
        "operateur": "Avis sur les frais et l'exécution...",
        "sceptique": "Avis sur les risques...",
        "visionnaire": "Avis sur les opportunités..."
      }},
      "synthese": "Résumé des avis du comité en 2 phrases...",
      "action": "BUY" | "SELL" | "HOLD",
      "ticker": "SYMBOLE",
      "amount_cad": 150.0,
      "reasoning": "Explication finale (basée sur la synthèse)"
    }}
    """
    # Tentatives multiples en cas de surcharge temporaire du serveur de l'IA
    models_to_try = ["gemini-2.5-flash", "gemini-2.0-flash"]
    for model_name in models_to_try:
        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json")
                )
                return json.loads(response.text)
            except Exception as e:
                print(f"Tentative échouée avec {model_name} (essai {attempt+1}/3): {e}")
                time.sleep(3)
                
    # Sécurité par défaut si l'API est injoignable
    return {"action": "HOLD", "ticker": "VFV.TO", "amount_cad": 0.0, "reasoning": "API temporairement occupée, attente de la prochaine exécution."}

def run_weekly_agent():
    portfolio = load_portfolio()
    watchlist = ["VFV.TO", "XEQT.TO", "SHOP.TO", "TD.TO", "AAPL", "MSFT"]
    
    decision = ask_trading_brain(portfolio, watchlist)
    print(f"Décision reçue : {decision}")

    if decision["action"] in ["BUY", "SELL"]:
        execute_order(
            portfolio,
            ticker=decision["ticker"],
            action=decision["action"],
            amount_cad=float(decision.get("amount_cad", 0)),
            reason=decision.get("reasoning", "")
        )

    total_val_cad = portfolio["cash_cad"]
    for sym, pos in portfolio["positions"].items():
        data = get_market_data(sym)
        if data:
            if data["is_us"]:
                total_val_cad += (pos["shares"] * data["price"]) * data["usd_to_cad"]
            else:
                total_val_cad += pos["shares"] * data["price"]

    portfolio["history_valuation"].append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_value_cad": round(total_val_cad, 2)
    })
    save_portfolio(portfolio)
    print(f"Valeur actuelle du portefeuille : {total_val_cad:.2f} $ CAD")

if __name__ == "__main__":
    run_weekly_agent()
