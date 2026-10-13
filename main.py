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
    Tu es un gestionnaire de portefeuille automatisé de type "Swing/Day Trader" opérant sur Wealthsimple avec un compte canadien (CAD).
    Capital initial : 1000 $ CAD.
    État actuel :
    - Liquidités disponibles : {portfolio['cash_cad']:.2f} $ CAD
    - Positions ouvertes (avec coût moyen et quantité) : {portfolio['positions']}
    
    Données de marché récentes (prix actuels, momentum, historique) :
    {json.dumps(market_snapshot, indent=2)}

    Règles strictes de trading quotidien (Maximiser les gains, minimiser les pertes) :
    1. Frais de change : 1,5% à l'achat et 1,5% à la vente sur les actions US (3% aller-retour). Sur du trading à court terme, ces frais détruisent la rentabilité. Privilégie massivement le marché canadien (.TO). N'achète du US que si le gain immédiat anticipé dépasse largement 3%.
    2. Préservation du capital : Tu agis 0 à 2 fois par jour. Si le marché est plat, incertain, ou sans momentum clair, choisis HOLD. Rester en cash est une position valide.
    3. Gestion des risques (30%) : Ne risque jamais plus de 30% du capital total sur un seul titre.
    4. Stop-Loss et Take-Profit (CRUCIAL) : Surveille activement tes "Positions ouvertes" en comparant leur coût avec le prix actuel du marché. 
       - Coupe tes pertes de manière stricte : si une position perd de son élan (ex: -3% à -5%), vends (SELL) pour limiter la casse.
       - Sécurise tes gains : si une position fait un bond rapide (ex: +3% à +7%), n'hésite pas à vendre (SELL) pour encaisser le profit. Ne t'attache pas aux actions.

    AVANT de prendre ta décision, réunis ton comité d'experts pour analyser la dynamique DU JOUR :
    
    1. L'Opérateur (Exécution) : Analyse le coût réel (frais FX) et la pertinence d'agir aujourd'hui. Vaut-il mieux encaisser un profit (SELL) ou conserver nos liquidités ?
    2. Le Sceptique (Risque) : Identifie les faiblesses immédiates. Est-ce qu'une de nos positions actuelles chute et nécessite une vente de protection d'urgence (Stop-Loss) ?
    3. Le Visionnaire (Occasion) : Identifie le momentum à très court terme. Y a-t-il une opportunité immédiate justifiant un achat (BUY) aujourd'hui ?

    Réponds EXCLUSIVEMENT avec un JSON au format exact suivant (aucun texte avant ou après) :
    {{
      "experts": {{
        "operateur": "Avis sur les frais, l'exécution et la gestion des liquidités du jour...",
        "sceptique": "Avis sur les risques immédiats, l'état des positions ouvertes et les déclenchements de Stop-Loss...",
        "visionnaire": "Avis sur le momentum du jour et les opportunités de Take-Profit ou d'achat..."
      }},
      "synthese": "Résumé des avis du comité en 2 phrases...",
      "action": "BUY" | "SELL" | "HOLD",
      "ticker": "SYMBOLE",
      "amount_cad": 150.0,
      "reasoning": "Explication finale (basée sur la synthèse, justifiant la logique d'achat, de prise de profit ou de coupe des pertes)"
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
