import csv
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

import yfinance as yf
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

DATA_DIR = "trading_agent_data"
PROMPTS_DIR = "prompts"
MARKET_TZ = ZoneInfo("America/Toronto")

# Univers enrichi : les 12 titres d'origine + 2 FNB défensifs canadiens (Obligations & Or) pour le bot Macro
WATCHLIST = [
    "VFV.TO", "XEQT.TO", "ZAG.TO", "CGL.TO",
    "SHOP.TO", "CSU.TO", "RY.TO", "TD.TO", "ATD.TO", "DOL.TO",
    "AAPL", "MSFT", "NVDA", "TSLA"
]

BROAD_ETFS = {"VFV.TO", "XEQT.TO", "ZAG.TO", "CGL.TO"}

# Configuration des 5 Bots et de leurs paramètres de risque déterministes
BOTS = {
    "momentum": {
        "name": "🔥 Trend Follower (Momentum)",
        "prompt_file": "momentum.txt",
        "max_pos_pct": 0.35,       # Max 35% par action individuelle
        "allow_us": True,
        "min_cash_pct": 0.10       # Garde au moins 10% de réserve
    },
    "value": {
        "name": "🏛️ Value Compounder (Buffett)",
        "prompt_file": "value.txt",
        "max_pos_pct": 0.35,
        "allow_us": True,
        "min_cash_pct": 0.10
    },
    "quant": {
        "name": "⚡ Mean Reverter (Quant)",
        "prompt_file": "quant.txt",
        "max_pos_pct": 0.30,       # Max 30% par anomalie statistique
        "allow_us": False,         # Interdiction stricte des titres US (frais FX 1.5% mortels en mean-reversion)
        "min_cash_pct": 0.15
    },
    "growth": {
        "name": "🚀 Growth Breakout (Tech)",
        "prompt_file": "growth.txt",
        "max_pos_pct": 0.35,
        "allow_us": True,
        "min_cash_pct": 0.10
    },
    "macro": {
        "name": "🌍 Macro Sentiment (Dalio)",
        "prompt_file": "macro.txt",
        "max_pos_pct": 0.35,       # Max 35% sur action individuelle (50% autorisé sur FNB indiciels/obligataires)
        "allow_us": False,         # Opère via les FNB et titres .TO à 0% de frais FX
        "min_cash_pct": 0.05
    }
}

# Modèles Gemini valides et disponibles dans l'API Google GenAI
MODELS_TO_TRY = ["gemini-2.5-flash", "gemini-2.5-pro"]


# =====================================================================
# SCHÉMAS PYDANTIC (Validation stricte des sorties de l'IA)
# =====================================================================
class ExpertsOpinion(BaseModel):
    operateur: str = Field(description="Vérification mathématique du PnL latent, des frais FX et de la taille de position.")
    sceptique: str = Field(description="Avocat du diable : identifie les faux signaux, le risque de baisse et conteste les excès.")
    visionnaire: str = Field(description="Identifie la meilleure opportunité selon les indicateurs de la stratégie.")


class TradingDecision(BaseModel):
    experts: ExpertsOpinion
    synthese: str = Field(description="Synthèse concise du débat en 2-3 phrases.")
    reasoning: str = Field(description="Justification mathématique et stratégique détaillée AVANT de prononcer la décision.")
    action: Literal["BUY", "SELL", "HOLD"]
    ticker: str = Field(description="Symbole boursier exact (ex: SHOP.TO) ou AUCUN si HOLD.")
    amount_cad: float = Field(default=0.0, ge=0.0, description="Montant en CAD à acheter ou vendre (0 si HOLD).")


# =====================================================================
# GESTION ATOMIQUE DES FICHIERS & JOURNAUX
# =====================================================================
def ensure_dirs() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def get_files(bot_id: str) -> dict[str, str]:
    return {
        "portfolio": os.path.join(DATA_DIR, f"portfolio_{bot_id}.json"),
        "trades": os.path.join(DATA_DIR, f"trades_{bot_id}.csv"),
        "logs": os.path.join(DATA_DIR, f"logs_{bot_id}.json")
    }


def save_json_atomic(filepath: str, data: dict | list) -> None:
    """Écriture atomique via fichier temporaire pour éviter toute corruption JSON."""
    ensure_dirs()
    dir_name = os.path.dirname(filepath) or "."
    with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tmp_file:
        json.dump(data, tmp_file, indent=2, ensure_ascii=False)
        tmp_name = tmp_file.name
    os.replace(tmp_name, filepath)


def load_portfolio(bot_id: str) -> dict:
    ensure_dirs()
    filepath = get_files(bot_id)["portfolio"]
    if not os.path.exists(filepath):
        initial_state = {
            "cash_cad": 1000.0,
            "positions": {},
            "history_valuation": [],
            "halted": False
        }
        save_json_atomic(filepath, initial_state)
        return initial_state
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        data.setdefault("cash_cad", 1000.0)
        data.setdefault("positions", {})
        data.setdefault("history_valuation", [])
        data.setdefault("halted", False)
        return data


def save_portfolio(bot_id: str, data: dict) -> None:
    save_json_atomic(get_files(bot_id)["portfolio"], data)


def log_trade(
    bot_id: str, date: str, ticker: str, action: str,
    shares: float, price: float, fx_rate: float,
    fee_cad: float, cash_left: float, reason: str
) -> None:
    filepath = get_files(bot_id)["trades"]
    file_exists = os.path.isfile(filepath)
    with open(filepath, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Date", "Ticker", "Action", "Shares", "Price", "FX_Rate", "Fee_CAD", "Cash_CAD_Left", "Reason"])
        writer.writerow([
            date, ticker, action,
            round(shares, 4), round(price, 2), round(fx_rate, 4),
            round(fee_cad, 2), round(cash_left, 2), reason
        ])


def log_ai_request(
    bot_id: str, date: str, model_used: str,
    market_snapshot: dict, decision: dict,
    order_executed: bool, risk_note: str = ""
) -> None:
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
        "amount_cad": round(float(decision.get("amount_cad", 0.0) or 0.0), 2),
        "order_executed": order_executed,
        "risk_engine_note": risk_note,
        "experts": decision.get("experts", {}),
        "synthese": decision.get("synthese", ""),
        "reasoning": decision.get("reasoning", "")
    }

    logs.append(log_entry)
    logs = logs[-100:]
    save_json_atomic(filepath, logs)


# =====================================================================
# COLLECTE DE DONNÉES QUANTITATIVES, FONDAMENTALES & MACRO
# =====================================================================
def safe_float(val, default=None, multiplier: float = 1.0) -> float | None:
    try:
        if val is None:
            return default
        res = float(val) * multiplier
        return round(res, 2)
    except (ValueError, TypeError):
        return default


def fetch_macro_context(usd_to_cad: float) -> dict:
    """Récupère les indicateurs macroéconomiques globaux (VIX, Taux US 10 ans)."""
    macro = {
        "usd_to_cad": round(usd_to_cad, 4),
        "vix_volatility_index": None,
        "us_10y_yield_pct": None,
        "regime_volatilite": "NORMAL"
    }
    try:
        vix_hist = yf.Ticker("^VIX").history(period="5d")
        if not vix_hist.empty:
            vix_val = float(vix_hist["Close"].iloc[-1])
            macro["vix_volatility_index"] = round(vix_val, 2)
            if vix_val >= 25.0:
                macro["regime_volatilite"] = "PANIQUE / RISK-OFF (VIX >= 25)"
            elif vix_val <= 15.0:
                macro["regime_volatilite"] = "CALME / RISK-ON (VIX <= 15)"
    except Exception:
        pass

    try:
        tnx_hist = yf.Ticker("^TNX").history(period="5d")
        if not tnx_hist.empty:
            macro["us_10y_yield_pct"] = round(float(tnx_hist["Close"].iloc[-1]), 2)
    except Exception:
        pass

    return macro


def fetch_all_market_data(watchlist: list[str]) -> tuple[dict, dict]:
    """Récupère 3 mois d'historique + données fondamentales en une passe pour les 5 bots."""
    usd_to_cad = 1.37
    try:
        fx = yf.Ticker("CADUSD=X").history(period="5d")
        if not fx.empty and float(fx["Close"].iloc[-1]) > 0:
            usd_to_cad = 1.0 / float(fx["Close"].iloc[-1])
    except Exception as e:
        print(f"[ALERTE FX] Erreur récupération CADUSD=X ({e}). Utilisation du taux de repli {usd_to_cad}.")

    macro_context = fetch_macro_context(usd_to_cad)
    market_data = {}
    positive_20d_count = 0

    for ticker in watchlist:
        try:
            stock = yf.Ticker(ticker)
            history = stock.history(period="3mo")
            if history.empty or len(history) < 6:
                continue

            closes = history["Close"]
            highs = history["High"]
            lows = history["Low"]
            volumes = history["Volume"]

            current_price = float(closes.iloc[-1])

            # 1. Variations exactes (1j, 5j sur 6 clôtures, 20j sur 21 clôtures)
            change_1d_pct = ((current_price - float(closes.iloc[-2])) / float(closes.iloc[-2])) * 100.0
            closes_6 = closes.tail(6).tolist()
            change_5d_pct = ((closes_6[-1] - closes_6[0]) / closes_6[0]) * 100.0
            idx_20 = -21 if len(closes) >= 21 else 0
            change_20d_pct = ((current_price - float(closes.iloc[idx_20])) / float(closes.iloc[idx_20])) * 100.0

            if change_20d_pct > 0:
                positive_20d_count += 1

            # 2. Moyennes mobiles, Z-Score (Mean Reversion) et Plus Haut 20j (Breakout)
            sma_20 = float(closes.tail(20).mean())
            sma_50 = float(closes.tail(50).mean()) if len(closes) >= 50 else sma_20
            std_20 = float(closes.tail(20).std())
            z_score_20 = ((current_price - sma_20) / std_20) if std_20 > 0 else 0.0

            high_20d = float(highs.tail(20).max())
            dist_high_20d_pct = ((current_price - high_20d) / high_20d) * 100.0

            # 3. RSI (14 jours)
            delta = closes.diff()
            gain = float(delta.clip(lower=0).tail(14).mean())
            loss = float((-delta.clip(upper=0)).tail(14).mean())
            rs = (gain / loss) if loss > 0 else 100.0
            rsi_14 = 100.0 - (100.0 / (1.0 + rs))

            # 4. Volatilité ATR (14 jours) en % du prix et Volume Relatif (RVOL)
            tr = (highs - lows).tail(14)
            atr_14_pct = (float(tr.mean()) / current_price) * 100.0 if current_price > 0 else 0.0
            avg_vol_20 = float(volumes.tail(20).mean())
            rel_volume = (float(volumes.iloc[-1]) / avg_vol_20) if avg_vol_20 > 0 else 1.0

            # 5. Données fondamentales (pour Value et Growth)
            fundamentals = {}
            try:
                info = stock.info or {}
                fundamentals = {
                    "pe_trailing": safe_float(info.get("trailingPE")),
                    "pe_forward": safe_float(info.get("forwardPE")),
                    "price_to_book": safe_float(info.get("priceToBook")),
                    "revenue_growth_yoy_pct": safe_float(info.get("revenueGrowth"), multiplier=100.0),
                    "earnings_growth_yoy_pct": safe_float(info.get("earningsGrowth"), multiplier=100.0),
                    "roe_pct": safe_float(info.get("returnOnEquity"), multiplier=100.0),
                    "dividend_yield_pct": safe_float(info.get("dividendYield"), multiplier=100.0),
                    "sector": info.get("sector", "ETF / Multi-Sector")
                }
            except Exception:
                fundamentals = {"sector": "Inconnu"}

            market_data[ticker] = {
                "price": round(current_price, 2),
                "is_us": not ticker.endswith(".TO"),
                "usd_to_cad": round(usd_to_cad, 4),
                "history_close_5d": [round(float(x), 2) for x in closes.tail(5).tolist()],
                "variation_1j_pct": round(change_1d_pct, 2),
                "variation_5j_pct": round(change_5d_pct, 2),
                "variation_20j_pct": round(change_20d_pct, 2),
                "sma_20": round(sma_20, 2),
                "sma_50": round(sma_50, 2),
                "trend_sma20_gt_sma50": bool(sma_20 >= sma_50),
                "z_score_20j": round(z_score_20, 2),
                "rsi_14": round(rsi_14, 1),
                "atr_14_pct": round(atr_14_pct, 2),
                "relative_volume": round(rel_volume, 2),
                "dist_high_20d_pct": round(dist_high_20d_pct, 2),
                "fundamentals": fundamentals
            }
        except Exception as e:
            print(f"Erreur téléchargement pour {ticker}: {e}")

    total_analyzed = max(len(market_data), 1)
    breadth_pct = round((positive_20d_count / total_analyzed) * 100.0, 1)
    macro_context["market_breadth_20d_positive_pct"] = f"{breadth_pct}%"
    macro_context["tendance_generale"] = (
        "HAUSSIÈRE (Risk-On)" if breadth_pct >= 55.0
        else ("BAISSIÈRE / DÉFENSIVE (Risk-Off)" if breadth_pct <= 40.0 else "NEUTRE / SÉLECTIVE")
    )
    return market_data, macro_context


# =====================================================================
# VALORISATION EXACTE ET ANALYSE DES POSITIONS OUVERTES
# =====================================================================
def compute_portfolio_metrics(portfolio: dict, raw_market_data: dict) -> tuple[float, dict]:
    """
    Calcule la valeur liquidative exacte du portefeuille (sans jamais tomber à 0$
    si un ticker manque) et prépare le rapport détaillé des positions pour le LLM.
    """
    total_val_cad = float(portfolio.get("cash_cad", 0.0))
    enriched_positions = {}

    for sym, pos in portfolio.get("positions", {}).items():
        shares = float(pos.get("shares", 0.0))
        if shares <= 0:
            continue
        cost_cad = float(pos.get("total_cost_cad", 0.0))
        avg_price_cad = float(pos.get("avg_price_cad", 0.0))
        d = raw_market_data.get(sym)

        if d and d.get("price", 0) > 0:
            price = float(d["price"])
            is_us = bool(d["is_us"])
            fx = float(d["usd_to_cad"]) if is_us else 1.0
            gross_val_cad = shares * price * fx
            exit_fee_cad = gross_val_cad * (0.015 if is_us else 0.0)
            net_val_cad = gross_val_cad - exit_fee_cad
            pos["last_known_val_cad"] = round(net_val_cad, 2)
        else:
            # Repli sécurisé si Yahoo Finance échoue momentanément sur ce titre
            net_val_cad = float(pos.get("last_known_val_cad", cost_cad))
            price = None
            is_us = not sym.endswith(".TO")

        total_val_cad += net_val_cad
        pnl_net_cad = net_val_cad - cost_cad
        pnl_net_pct = ((net_val_cad - cost_cad) / cost_cad) * 100.0 if cost_cad > 0 else 0.0

        enriched_positions[sym] = {
            "shares": round(shares, 4),
            "avg_cost_per_share_cad": round(avg_price_cad, 2),
            "current_market_price_native": price,
            "total_cost_cad": round(cost_cad, 2),
            "current_net_value_cad": round(net_val_cad, 2),
            "unrealized_pnl_net_cad": round(pnl_net_cad, 2),
            "unrealized_pnl_net_pct": f"{pnl_net_pct:+.2f}%",
            "unrealized_pnl_net_pct_num": round(pnl_net_pct, 2),
            "is_us_stock_with_fx_fee": is_us,
            "opened_at": pos.get("opened_at", "Inconnu")
        }

    # Ajout du poids en % de chaque position dans le portefeuille total
    for sym, ep in enriched_positions.items():
        ep["portfolio_weight_pct"] = round((ep["current_net_value_cad"] / total_val_cad) * 100.0, 1) if total_val_cad > 0 else 0.0

    return round(total_val_cad, 2), enriched_positions


# =====================================================================
# MOTEUR DE RISQUE DÉTERMINISTE & EXÉCUTION DES ORDRES
# =====================================================================
def validate_and_clamp_order(
    bot_id: str,
    bot_cfg: dict,
    portfolio: dict,
    enriched_positions: dict,
    total_val_cad: float,
    decision: dict,
    raw_market_data: dict
) -> tuple[str, str, float, str]:
    """
    Pare-feu déterministe qui vérifie, plafonne ou bloque les ordres de l'IA
    avant toute exécution. Un LLM ne peut jamais contourner ces règles.
    """
    action = decision.get("action", "HOLD")
    ticker = decision.get("ticker", "AUCUN")
    requested_amount = float(decision.get("amount_cad", 0.0) or 0.0)

    if portfolio.get("halted", False):
        return "HOLD", "AUCUN", 0.0, "Portefeuille suspendu (Drawdown max dépassé)."

    if action == "HOLD" or ticker not in raw_market_data:
        return "HOLD", "AUCUN", 0.0, "Décision HOLD ou symbole hors univers."

    d = raw_market_data[ticker]
    is_us = d["is_us"]
    cash_cad = float(portfolio["cash_cad"])

    if action == "BUY":
        # 1. Interdiction des titres US pour les bots non autorisés (Quant / Macro)
        if is_us and not bot_cfg.get("allow_us", True):
            return "HOLD", ticker, 0.0, f"REJET RISQUE : {bot_id} n'est pas autorisé à acheter des titres US ({ticker}) soumis à 1.5% de frais FX."

        # 2. Respect de la réserve minimale de liquidités
        min_cash_cad = total_val_cad * float(bot_cfg.get("min_cash_pct", 0.10))
        available_for_trade = max(0.0, cash_cad - min_cash_cad)
        if available_for_trade < 50.0:
            return "HOLD", ticker, 0.0, f"REJET RISQUE : Liquidités disponibles hors réserve ({available_for_trade:.2f}$ CAD) inférieures au minimum de 50$."

        # 3. Plafond de concentration par ligne (35% par action, ou 50% sur FNB indiciel large)
        max_weight = 0.50 if ticker in BROAD_ETFS else float(bot_cfg.get("max_pos_pct", 0.35))
        max_line_cad = total_val_cad * max_weight
        current_line_cad = enriched_positions.get(ticker, {}).get("current_net_value_cad", 0.0)
        remaining_line_capacity = max(0.0, max_line_cad - current_line_cad)

        if remaining_line_capacity < 50.0:
            return "HOLD", ticker, 0.0, f"REJET RISQUE : Poids maximal atteint sur {ticker} ({current_line_cad:.2f}$ / plafond {max_line_cad:.2f}$ CAD)."

        # 4. Calcul du montant final autorisé
        clamped_amount = min(requested_amount, available_for_trade, remaining_line_capacity, cash_cad)
        min_order = 150.0 if is_us else 60.0
        if clamped_amount < min_order:
            return "HOLD", ticker, 0.0, f"REJET RISQUE : Montant ajusté ({clamped_amount:.2f}$ CAD) inférieur au seuil minimal ({min_order}$ CAD)."

        note = "Ordre BUY validé."
        if clamped_amount < requested_amount:
            note = f"Montant BUY plafonné par le Risk Manager de {requested_amount:.2f}$ à {clamped_amount:.2f}$ CAD (limite de concentration/réserve)."
        return "BUY", ticker, round(clamped_amount, 2), note

    elif action == "SELL":
        if ticker not in enriched_positions:
            return "HOLD", ticker, 0.0, f"REJET RISQUE : Impossible de vendre {ticker} (non détenu en portefeuille)."

        pos_info = enriched_positions[ticker]
        pnl_pct = float(pos_info["unrealized_pnl_net_pct_num"])

        # Protection contre les ventes sur un micro-bruit compris entre -1.2% et +1.2%
        if -1.2 < pnl_pct < 1.2:
            return "HOLD", ticker, 0.0, f"REJET RISQUE : Vente de {ticker} bloquée (PnL latent net de {pnl_pct:+.2f}% trop proche de 0%, rotation inutile)."

        current_val = float(pos_info["current_net_value_cad"])
        sell_amount = current_val if requested_amount <= 0 or requested_amount >= current_val * 0.85 else requested_amount
        return "SELL", ticker, round(sell_amount, 2), f"Ordre SELL validé (PnL latent net vérifié : {pnl_pct:+.2f}%)."

    return "HOLD", "AUCUN", 0.0, "Action non reconnue."


def execute_order(
    bot_id: str, portfolio: dict, ticker: str, action: str,
    amount_cad: float, reason: str, market_data: dict, today: str
) -> bool:
    data = market_data.get(ticker)
    if not data or data.get("price", 0) <= 0:
        return False

    price = float(data["price"])
    is_us = bool(data["is_us"])
    usd_to_cad = float(data["usd_to_cad"])
    fx_fee_rate = 0.015 if is_us else 0.0

    if action == "BUY":
        if amount_cad <= 0 or amount_cad > portfolio["cash_cad"] + 1e-6:
            return False

        amount_cad = min(amount_cad, float(portfolio["cash_cad"]))
        fee_cad = amount_cad * fx_fee_rate
        net_invest_cad = amount_cad - fee_cad
        shares_bought = (net_invest_cad / usd_to_cad) / price if is_us else net_invest_cad / price

        portfolio["cash_cad"] = round(float(portfolio["cash_cad"]) - amount_cad, 4)
        pos = portfolio["positions"].get(ticker, {"shares": 0.0, "total_cost_cad": 0.0, "opened_at": today})
        pos["shares"] = round(float(pos["shares"]) + shares_bought, 6)
        pos["total_cost_cad"] = round(float(pos["total_cost_cad"]) + amount_cad, 4)
        pos["avg_price_cad"] = round(pos["total_cost_cad"] / pos["shares"], 4)
        portfolio["positions"][ticker] = pos

        log_trade(bot_id, today, ticker, "BUY", shares_bought, price, usd_to_cad if is_us else 1.0, fee_cad, portfolio["cash_cad"], reason)
        return True

    elif action == "SELL":
        pos = portfolio["positions"].get(ticker)
        if not pos or float(pos.get("shares", 0)) <= 0:
            return False

        total_shares = float(pos["shares"])
        total_gross_cad = (total_shares * price) * usd_to_cad if is_us else total_shares * price

        # Support des ventes partielles ou totales
        sell_fraction = min(1.0, amount_cad / total_gross_cad) if (amount_cad > 0 and total_gross_cad > 0) else 1.0
        if sell_fraction >= 0.90:
            sell_fraction = 1.0

        shares_to_sell = total_shares * sell_fraction
        gross_cad = (shares_to_sell * price) * usd_to_cad if is_us else shares_to_sell * price
        fee_cad = gross_cad * fx_fee_rate
        net_cad = gross_cad - fee_cad

        portfolio["cash_cad"] = round(float(portfolio["cash_cad"]) + net_cad, 4)

        if sell_fraction >= 0.9999:
            del portfolio["positions"][ticker]
        else:
            pos["shares"] = round(total_shares - shares_to_sell, 6)
            pos["total_cost_cad"] = round(float(pos["total_cost_cad"]) * (1.0 - sell_fraction), 4)
            pos["avg_price_cad"] = round(pos["total_cost_cad"] / pos["shares"], 4)
            portfolio["positions"][ticker] = pos

        log_trade(bot_id, today, ticker, "SELL", shares_to_sell, price, usd_to_cad if is_us else 1.0, fee_cad, portfolio["cash_cad"], reason)
        return True

    return False


# =====================================================================
# INTERROGATION DU CERVEAU IA (GEMINI)
# =====================================================================
def read_strategy_prompt(filename: str) -> str:
    filepath = os.path.join(PROMPTS_DIR, filename)
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    print(f"ATTENTION: Fichier {filepath} introuvable. Utilisation d'un prompt par défaut.")
    return "Tu es un gestionnaire de portefeuille discipliné opérant sur un compte CAD Wealthsimple."


def ask_trading_brain(
    client: genai.Client,
    bot_id: str,
    bot_cfg: dict,
    portfolio: dict,
    enriched_positions: dict,
    total_val_cad: float,
    macro_context: dict,
    market_snapshot: dict,
    strategy_text: str
) -> tuple[dict, str]:
    max_pos_cad = round(total_val_cad * float(bot_cfg.get("max_pos_pct", 0.35)), 2)

    prompt = f"""
=== INSTRUCTIONS DE STRATÉGIE SPÉCIFIQUE ===
{strategy_text}

=== RÈGLES DU MOTEUR DE RISQUE DÉTERMINISTE (IMPOSSIBLE À CONTOURNER) ===
- Valeur totale actuelle de ton portefeuille : {total_val_cad:.2f} $CAD (Capital initial : 1000.00$ CAD)
- Liquidités disponibles (Cash) : {portfolio['cash_cad']:.2f} $ CAD
- Taille maximale autorisée sur une action individuelle : {max_pos_cad:.2f} $ CAD ({int(bot_cfg['max_pos_pct']*100)}% du portefeuille)
- Autorisation d'acheter des actions US (frais FX 1.5% par sens) : {"OUI (uniquement si conviction exceptionnelle)" if bot_cfg['allow_us'] else "NON (INTERDICTION STRICTE, 100% titres .TO uniquement)"}
- IMPORTANT : Ne confonds JAMAIS la variation sur 5 jours d'une action (variation_5j_pct) avec ton gain/perte latent réel sur une position ouverte (unrealized_pnl_net_pct). Utilise EXCLUSIVEMENT le champ `unrealized_pnl_net_pct` ci-dessous pour juger de la rentabilité d'une ligne en portefeuille !

=== ÉTAT EXACT DE TES POSITIONS OUVERTES (Calculé par Python, Net de frais FX) ===
{json.dumps(enriched_positions, indent=2, ensure_ascii=False)}

=== CONTEXTE MACROÉCONOMIQUE DU JOUR ===
{json.dumps(macro_context, indent=2, ensure_ascii=False)}

=== DONNÉES QUANTITATIVES & FONDAMENTALES DU MARCHÉ ({len(market_snapshot)} TITRES) ===
{json.dumps(market_snapshot, indent=2, ensure_ascii=False)}

=== PROCESSUS DE DÉLIBÉRATION OBLIGATOIRE ===
Fais débattre tes 3 experts (L'Opérateur, Le Sceptique, Le Visionnaire).
Si aucune opportunité ne respecte strictement tous tes critères mathématiques, ou si tes positions actuelles suivent leur plan, choisis "HOLD". L'inaction disciplinée est préférable à un achat médiocre.
"""

    for model_name in MODELS_TO_TRY:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=TradingDecision,
                        temperature=0.1
                    )
                )
                parsed = TradingDecision.model_validate_json(response.text)
                return parsed.model_dump(), model_name
            except ValidationError as ve:
                print(f"[{bot_id}] Erreur de validation JSON sur {model_name}: {ve}")
            except Exception as e:
                print(f"[{bot_id}] Essai échoué sur {model_name} (tentative {attempt+1}): {e}")
                time.sleep(3)

    return {
        "experts": {
            "operateur": "API indisponible.",
            "sceptique": "API indisponible.",
            "visionnaire": "API indisponible."
        },
        "synthese": "Impossible de joindre les modèles Gemini lors de cette exécution.",
        "reasoning": "Mise en attente automatique de sécurité suite à une erreur API.",
        "action": "HOLD",
        "ticker": "AUCUN",
        "amount_cad": 0.0
    }, "erreur-api"


# =====================================================================
# CONTRÔLE DU CALENDRIER BOURSIER & ORCHESTRATION PRINCIPALE
# =====================================================================
def can_run_now(force: bool = False) -> tuple[bool, str]:
    now_et = datetime.now(MARKET_TZ)
    if force:
        return True, f"Exécution forcée (--force) à {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}"

    if now_et.weekday() >= 5:
        return False, f"Marché fermé (Week-end : {now_et.strftime('%A')}). Utilisez --force pour tester."

    market_open = now_et.replace(hour=9, minute=45, second=0, microsecond=0)
    market_close = now_et.replace(hour=15, minute=55, second=0, microsecond=0)
    if not (market_open <= now_et <= market_close):
        return (
            False,
            f"Hors de la fenêtre d'exécution sécurisée (09h45 - 15h55 HE, heure actuelle : {now_et.strftime('%H:%M HE')}). "
            "Utilisez `python main.py --force` pour forcer un test hors séance."
        )
    return True, f"Séance boursière active ({now_et.strftime('%Y-%m-%d %H:%M:%S %Z')})"


def already_traded_today(portfolio: dict, today_date_str: str) -> bool:
    """Vérifie si le bot a déjà été évalué aujourd'hui pour éviter les doublons d'ordres."""
    history = portfolio.get("history_valuation", [])
    if not history:
        return False
    last_eval_date = str(history[-1].get("date", ""))[:10]
    return last_eval_date == today_date_str


def run_arena() -> None:
    force_run = "--force" in sys.argv
    allowed, msg = can_run_now(force=force_run)
    print(f"[STATUT HORLOGE BOURSIÈRE] {msg}")
    if not allowed:
        return

    print("Téléchargement et calcul des indicateurs techniques, fondamentaux et macro...")
    raw_market_data, macro_context = fetch_all_market_data(WATCHLIST)
    if not raw_market_data:
        print("[ERREUR CRITIQUE] Aucune donnée de marché récupérée. Arrêt sécurisé.")
        return

    # Résumé structuré complet transmis aux bots
    market_snapshot = {}
    for sym, d in raw_market_data.items():
        market_snapshot[sym] = {
            "prix_actuel": d["price"],
            "devise_et_frais": "USD (Frais FX 1.5% achat + 1.5% vente)" if d["is_us"] else "CAD (0% Frais)",
            "historique_5j": d["history_close_5d"],
            "variation_1j_pct": f"{d['variation_1j_pct']:+.2f}%",
            "variation_5j_pct": f"{d['variation_5j_pct']:+.2f}%",
            "variation_20j_pct": f"{d['variation_20j_pct']:+.2f}%",
            "indicateurs_techniques": {
                "sma_20": d["sma_20"],
                "sma_50": d["sma_50"],
                "tendance_sma20_sup_sma50": d["trend_sma20_gt_sma50"],
                "rsi_14": d["rsi_14"],
                "z_score_20j": d["z_score_20j"],
                "volatilite_atr_14_pct": f"{d['atr_14_pct']}%",
                "volume_relatif_20j": d["relative_volume"],
                "distance_plus_haut_20j_pct": f"{d['dist_high_20d_pct']:+.2f}%"
            },
            "fondamentaux": d["fundamentals"]
        }

    now_et = datetime.now(MARKET_TZ)
    today_str = now_et.strftime("%Y-%m-%d %H:%M:%S")
    today_date_only = now_et.strftime("%Y-%m-%d")

    client = genai.Client()

    for index, (bot_id, bot_cfg) in enumerate(BOTS.items()):
        print(f"\n--- Exécution de {bot_cfg['name']} ---")
        portfolio = load_portfolio(bot_id)

        if not force_run and already_traded_today(portfolio, today_date_only):
            print(f"[{bot_id}] Déjà exécuté aujourd'hui ({today_date_only}). Ignoré (utilisez --force pour outrepasser).")
            continue

        total_val_before, enriched_positions = compute_portfolio_metrics(portfolio, raw_market_data)

        # Coupe-circuit automatique si le portefeuille perd plus de 18% depuis un pic (ou passe sous 820$)
        peak_val = max([1000.0] + [float(h.get("total_value_cad", 1000.0)) for h in portfolio.get("history_valuation", [])])
        drawdown_pct = ((total_val_before - peak_val) / peak_val) * 100.0
        if drawdown_pct <= -18.0:
            portfolio["halted"] = True
            print(f"[{bot_id}] COUPE-CIRCUIT ACTIVÉ : Drawdown de {drawdown_pct:.2f}% (Valeur: {total_val_before:.2f}$ CAD).")

        strategy_text = read_strategy_prompt(bot_cfg["prompt_file"])
        decision, model_used = ask_trading_brain(
            client=client,
            bot_id=bot_id,
            bot_cfg=bot_cfg,
            portfolio=portfolio,
            enriched_positions=enriched_positions,
            total_val_cad=total_val_before,
            macro_context=macro_context,
            market_snapshot=market_snapshot,
            strategy_text=strategy_text
        )

        # Validation déterministe par le Risk Manager avant toute exécution
        safe_action, safe_ticker, safe_amount, risk_note = validate_and_clamp_order(
            bot_id=bot_id,
            bot_cfg=bot_cfg,
            portfolio=portfolio,
            enriched_positions=enriched_positions,
            total_val_cad=total_val_before,
            decision=decision,
            raw_market_data=raw_market_data
        )

        print(
            f"[{bot_id}] IA ({model_used}) a proposé : {decision.get('action')} {decision.get('ticker')} ({decision.get('amount_cad')}$ CAD)\n"
            f"[{bot_id}] Décision Risk Manager : {safe_action} {safe_ticker} ({safe_amount:.2f}$ CAD) -> {risk_note}"
        )

        order_executed = False
        if safe_action in ["BUY", "SELL"] and safe_ticker in raw_market_data:
            reason_with_note = f"{decision.get('reasoning', '')} [{risk_note}]"
            order_executed = execute_order(
                bot_id=bot_id,
                portfolio=portfolio,
                ticker=safe_ticker,
                action=safe_action,
                amount_cad=safe_amount,
                reason=reason_with_note,
                market_data=raw_market_data,
                today=today_str
            )

        decision["action"] = safe_action
        decision["ticker"] = safe_ticker
        decision["amount_cad"] = safe_amount
        log_ai_request(bot_id, today_str, model_used, market_snapshot, decision, order_executed, risk_note)

        # Recalcul de la valeur finale après transaction éventuelle
        total_val_after, _ = compute_portfolio_metrics(portfolio, raw_market_data)
        portfolio["history_valuation"].append({
            "date": today_str,
            "total_value_cad": round(total_val_after, 2)
        })
        save_portfolio(bot_id, portfolio)

        if index < len(BOTS) - 1:
            time.sleep(6)


if __name__ == "__main__":
    run_arena()
