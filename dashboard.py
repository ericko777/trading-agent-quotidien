import streamlit as st
import pandas as pd
import json
import os
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
import datetime

# --- CONFIGURATION PAGE MOBILE-FIRST (GALAXY S24+) ---
st.set_page_config(
    page_title="AI Trading Arena",
    page_icon="🏆",
    layout="centered",
    initial_sidebar_state="collapsed"
)

DATA_DIR = "trading_agent_data"
PROMPTS_DIR = "prompts"
CAPITAL_INITIAL = 1000.0

BOTS = {
    "momentum": {"name": "Trend Follower", "icon": "🔥", "style": "Momentum", "color": "#FF6B35", "prompt": "momentum.txt"},
    "value": {"name": "Value Compounder", "icon": "🏛️", "style": "Buffett", "color": "#3B82F6", "prompt": "value.txt"},
    "quant": {"name": "Mean Reverter", "icon": "⚡", "style": "Quant Scalper", "color": "#10B981", "prompt": "quant.txt"},
    "growth": {"name": "Growth Breakout", "icon": "🚀", "style": "Hyper-Tech", "color": "#A855F7", "prompt": "growth.txt"},
    "macro": {"name": "Macro Rotator", "icon": "🌍", "style": "Dalio", "color": "#F59E0B", "prompt": "macro.txt"}
}

# --- FONCTIONS UTILITAIRES TEMPORELLES ---
def to_qc_time(date_str):
    if not date_str or date_str == "Aucune": return date_str
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return (dt - datetime.timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
    except:
        return date_str

# --- CSS SUR MESURE POUR ÉCRAN AMOLED ---
st.markdown("""
<style>
    header[data-testid="stHeader"] { background: transparent !important; height: 2.5rem !important; }
    .block-container { padding-top: 4.2rem !important; padding-bottom: 3rem !important; padding-left: 0.9rem !important; padding-right: 0.9rem !important; max-width: 520px !important; }
    .hero-card { background: linear-gradient(145deg, #0f172a 0%, #1e293b 100%); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 18px; padding: 18px; margin-top: 0.5rem; margin-bottom: 16px; box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4); }
    .hero-title { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 1.2px; color: #94a3b8; margin-bottom: 4px; font-weight: 600; }
    .hero-value { font-size: 2.0rem; font-weight: 800; color: #f8fafc; line-height: 1.15; }
    .hero-sub { font-size: 0.88rem; margin-top: 6px; font-weight: 600; }
    .kpi-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-top: 12px; margin-bottom: 14px; }
    .kpi-box { background: #111827; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 14px; padding: 12px 14px; }
    .kpi-label { font-size: 0.72rem; color: #9ca3af; text-transform: uppercase; margin-bottom: 4px; }
    .kpi-num { font-size: 1.18rem; font-weight: 700; color: #f3f4f6; }
    .rank-card { background: #111827; border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 14px; padding: 12px 14px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
    .rank-left { display: flex; align-items: center; gap: 10px; }
    .rank-medal { font-size: 1.35rem; min-width: 28px; text-align: center; }
    .rank-name { font-weight: 700; font-size: 0.95rem; color: #f8fafc; }
    .rank-meta { font-size: 0.74rem; color: #94a3b8; }
    .rank-right { text-align: right; }
    .rank-val { font-weight: 800; font-size: 1.02rem; color: #f8fafc; }
    .pos-green { color: #10b981 !important; font-weight: 700; }
    .neg-red { color: #ef4444 !important; font-weight: 700; }
    .neutral-grey { color: #94a3b8 !important; font-weight: 600; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 0.70rem; font-weight: 700; }
    .badge-buy { background: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
    .badge-sell { background: rgba(239, 68, 68, 0.18); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }
    .badge-hold { background: rgba(148, 163, 184, 0.15); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.3); }
    .equation-bar { background: rgba(30, 41, 59, 0.7); border-left: 4px solid #3b82f6; border-radius: 10px; padding: 10px 12px; font-size: 0.82rem; color: #e2e8f0; margin-bottom: 14px; }
    .expert-box { border-radius: 12px; padding: 11px 13px; margin-bottom: 8px; font-size: 0.85rem; line-height: 1.45; }
    .exp-op { background: rgba(59, 130, 246, 0.12); border-left: 3px solid #3b82f6; color: #dbeafe; }
    .exp-sc { background: rgba(245, 158, 11, 0.12); border-left: 3px solid #f59e0b; color: #fef3c7; }
    .exp-vi { background: rgba(16, 185, 129, 0.12); border-left: 3px solid #10b981; color: #d1fae5; }
</style>
""", unsafe_allow_html=True)

# --- FONCTIONS DONNÉES EN DIRECT (Cache dynamique) ---
@st.cache_data(ttl=300, show_spinner=False)
def get_live_prices(tickers_tuple):
    prices = {}
    usd_to_cad = 1.38
    try:
        fx = yf.Ticker("CADUSD=X").history(period="5d")
        if not fx.empty: usd_to_cad = float(1.0 / fx["Close"].iloc[-1])
    except Exception: pass
    for t in tickers_tuple:
        try:
            h = yf.Ticker(t).history(period="5d")
            if not h.empty: prices[t] = float(h["Close"].iloc[-1])
        except Exception: pass
    return prices, usd_to_cad

@st.cache_data(ttl=300, show_spinner=False)
def get_intraday_stock_data(ticker):
    """Télécharge l'historique détaillé (Heure par heure) d'une action pour le graphique Candlestick."""
    try:
        stock = yf.Ticker(ticker)
        df = stock.history(period="7d", interval="1h")
        if not df.empty:
            df.index = df.index.tz_convert('America/Toronto')
            df.reset_index(inplace=True)
            return df
    except Exception:
        pass
    return pd.DataFrame()

def format_badge(action_str):
    if "BUY" in action_str: return f'<span class="badge badge-buy">🟢 {action_str}</span>'
    elif "SELL" in action_str: return f'<span class="badge badge-sell">🔴 {action_str}</span>'
    return f'<span class="badge badge-hold">⏸️ {action_str}</span>'

# --- 1. LECTURE DES DONNÉES ET COLLECTE DES TICKERS POSSÉDÉS UNIQUEMENT ---
all_open_tickers = set() # MODIFICATION : On part de zéro au lieu de prendre toute la Watchlist
raw_portfolios = {}
raw_trades = {}
raw_logs = {}

for bot_id in BOTS.keys():
    p_file = os.path.join(DATA_DIR, f"portfolio_{bot_id}.json")
    if os.path.exists(p_file):
        with open(p_file, "r", encoding="utf-8") as f:
            p_data = json.load(f)
        raw_portfolios[bot_id] = p_data
        
        # On ajoute UNIQUEMENT les actions qui sont actuellement détenues par les bots
        for sym in p_data.get("positions", {}).keys():
            all_open_tickers.add(sym)
            
    t_file = os.path.join(DATA_DIR, f"trades_{bot_id}.csv")
    if os.path.exists(t_file): raw_trades[bot_id] = pd.read_csv(t_file)
        
    l_file = os.path.join(DATA_DIR, f"logs_{bot_id}.json")
    if os.path.exists(l_file):
        with open(l_file, "r", encoding="utf-8") as f:
            raw_logs[bot_id] = json.load(f)

# On va chercher les prix en direct uniquement pour les actions détenues
live_prices, live_usd_to_cad = get_live_prices(tuple(all_open_tickers))
now_qc = datetime.datetime.utcnow() - datetime.timedelta(hours=4)
now_str_qc = now_qc.strftime("%Y-%m-%d %H:%M:%S")

# --- 2. CALCUL DU CLASSEMENT EN DIRECT ---
recap_list = []
courbes_list = []

for bot_id, info in BOTS.items():
    if bot_id not in raw_portfolios: continue
        
    p_data = raw_portfolios[bot_id]
    cash_cad = float(p_data["cash_cad"])
    val_actuelle_live = cash_cad
    
    for ticker, pos in p_data.get("positions", {}).items():
        shares = float(pos["shares"])
        is_us = not ticker.endswith(".TO")
        if ticker in live_prices:
            val_actuelle_live += (shares * live_prices[ticker] * live_usd_to_cad) if is_us else (shares * live_prices[ticker])
        else:
            val_actuelle_live += float(pos["total_cost_cad"])

    df_t = raw_trades.get(bot_id)
    frais = float(df_t["Fee_CAD"].sum()) if df_t is not None else 0.0
    nb_trades = len(df_t) if df_t is not None else 0

    l_data = raw_logs.get(bot_id, [])
    nb_requetes = len(l_data)
    derniere_action = l_data[-1].get("action", "HOLD") if nb_requetes > 0 else "HOLD"
    dernier_ticker = l_data[-1].get("ticker", "-") if nb_requetes > 0 else "-"
    derniere_date = to_qc_time(l_data[-1].get("date", "Aucune")) if nb_requetes > 0 else "Aucune"

    gain_net = val_actuelle_live - CAPITAL_INITIAL
    roi_pct = (gain_net / CAPITAL_INITIAL) * 100.0
    cash_pct = (cash_cad / val_actuelle_live) * 100.0 if val_actuelle_live > 0 else 100.0

    recap_list.append({
        "bot_id": bot_id, "icon": info["icon"], "name": info["name"], "style": info["style"],
        "val": val_actuelle_live, "gain_net": gain_net, "roi_pct": roi_pct, "frais": frais,
        "trades": nb_trades, "requetes": nb_requetes, "cash_cad": cash_cad, "cash_pct": cash_pct,
        "last_action": derniere_action, "last_ticker": dernier_ticker, "last_date": derniere_date
    })

    for item in p_data.get("history_valuation", []):
        courbes_list.append({
            "Date": to_qc_time(item["date"]),
            "Bot": f"{info['icon']} {info['name']}",
            "Valeur (CAD)": float(item["total_value_cad"]),
            "Type": "Run"
        })
    
    courbes_list.append({
        "Date": now_str_qc, 
        "Bot": f"{info['icon']} {info['name']}",
        "Valeur (CAD)": round(val_actuelle_live, 2),
        "Type": "Live"
    })

if not recap_list:
    st.markdown("""<div class="hero-card"><div class="hero-title">⏳ Initialisation de l'Arène</div><div class="hero-value">En attente du 1er Run</div></div>""", unsafe_allow_html=True)
    st.stop()

df_recap = pd.DataFrame(recap_list).sort_values(by="val", ascending=False).reset_index(drop=True)

# --- 3. AFFICHAGE BANDEAU ET PODIUM ---
capital_global = CAPITAL_INITIAL * len(df_recap)
val_globale = df_recap["val"].sum()
gain_global = val_globale - capital_global
roi_global = (gain_global / capital_global) * 100.0
frais_globaux = df_recap["frais"].sum()
leader = df_recap.iloc[0]
c_glob = "pos-green" if gain_global >= 0 else "neg-red"
s_glob = "+" if gain_global >= 0 else ""

st.markdown(f"""
<div class="hero-card">
    <div style="display:flex; justify-content:space-between; align-items:center;">
        <div class="hero-title">🏆 Fonds Global ({len(df_recap)} Bots Actifs)</div>
        <div style="font-size:0.70rem; color:#64748b;">🟢 Live Market</div>
    </div>
    <div class="hero-value">{val_globale:,.2f} $ <span style="font-size:0.95rem; font-weight:500; color:#94a3b8;">CAD</span></div>
    <div class="hero-sub {c_glob}">{s_glob}{gain_global:,.2f} $ ({s_glob}{roi_global:.2f}%) depuis le départ</div>
    <div class="kpi-grid" style="margin-bottom:0px; margin-top:14px;">
        <div class="kpi-box" style="padding:9px 12px;"><div class="kpi-label">👑 Leader Actuel</div><div style="font-size:0.95rem; font-weight:700; color:#f8fafc;">{leader['icon']} {leader['name']}</div></div>
        <div class="kpi-box" style="padding:9px 12px;"><div class="kpi-label">💸 Frais WS Totaux</div><div style="font-size:0.95rem; font-weight:700; color:#f87171;">-{frais_globaux:.2f} $</div></div>
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown("### 🏁 Classement en Direct")
medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
for idx, row in df_recap.iterrows():
    medal = medals[idx] if idx < len(medals) else f"#{idx+1}"
    c_class = "pos-green" if row["gain_net"] >= 0 else "neg-red"
    sign = "+" if row["gain_net"] >= 0 else ""
    act_str = f"{row['last_action']} {row['last_ticker']}" if row["last_action"] != "HOLD" else "HOLD"
    
    st.markdown(f"""
    <div class="rank-card">
        <div class="rank-left">
            <div class="rank-medal">{medal}</div>
            <div>
                <div class="rank-name">{row['icon']} {row['name']}</div>
                <div class="rank-meta">{row['style']} • Investi: {100.0 - row['cash_pct']:.0f}%</div>
            </div>
        </div>
        <div class="rank-right">
            <div class="rank-val">{row['val']:.2f} $</div>
            <div style="font-size:0.78rem;" class="{c_class}">{sign}{row['gain_net']:.2f}$ ({sign}{row['roi_pct']:.2f}%)</div>
            <div style="margin-top:3px;">{format_badge(act_str)}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- 4. TERMINAL DE MARCHÉ : GRAPHIQUE DYNAMIQUE ---
st.divider()
st.markdown("<h3 style='margin-bottom:8px;'>📊 Terminal Graphique</h3>", unsafe_allow_html=True)

options_vue = ["Tous (Portefeuilles)"] + sorted(list(all_open_tickers))
vue_choisie = st.selectbox("Sélectionne ce que tu veux analyser :", options_vue, label_visibility="collapsed")

if vue_choisie == "Tous (Portefeuilles)":
    nb_points = st.radio("Points affichés :", options=[10, 20, 50, 100, "Tous"], horizontal=True, label_visibility="collapsed")
    df_courbes = pd.DataFrame(courbes_list)
    
    if nb_points != "Tous":
        df_courbes = df_courbes.groupby("Bot").tail(int(nb_points)).reset_index(drop=True)

    fig_comp = px.line(df_courbes, x="Date", y="Valeur (CAD)", color="Bot", markers=True)
    fig_comp.add_hline(y=CAPITAL_INITIAL, line_dash="dot", line_color="rgba(255,255,255,0.35)")
    
    for trace in fig_comp.data:
        bot_df = df_courbes[df_courbes["Bot"] == trace.name]
        types = bot_df["Type"].tolist()
        symbols = ['circle' if t == "Run" else 'circle-open' for t in types]
        sizes = [6 if t == "Run" else 10 for t in types]
        trace.update(marker=dict(symbol=symbols, size=sizes, line=dict(width=2, color=trace.line.color)))

    fig_comp.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,24,39,0.6)",
        height=320, margin=dict(t=10, l=5, r=5, b=10), dragmode=False,
        xaxis=dict(fixedrange=True, title="", showgrid=False),
        yaxis=dict(fixedrange=True, title="CAD ($)", gridcolor="rgba(255,255,255,0.06)"),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title="")
    )
    st.plotly_chart(fig_comp, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False})

else:
    # Affichage du graphique boursier détaillé (Chandelier) pour une action spécifique
    st.caption(f"Historique intraday (1 Heure) pour **{vue_choisie}**")
    df_stock = get_intraday_stock_data(vue_choisie)
    
    if not df_stock.empty:
        # Calcul du Minimum et Maximum pour ajuster l'axe Y
        min_price = df_stock['Low'].min()
        max_price = df_stock['High'].max()
        # Ajout d'une marge de 5% en haut et en bas
        margin = (max_price - min_price) * 0.05
        y_min = min_price - margin
        y_max = max_price + margin

        fig_stock = go.Figure(data=[go.Candlestick(
            x=df_stock['Datetime'],
            open=df_stock['Open'],
            high=df_stock['High'],
            low=df_stock['Low'],
            close=df_stock['Close'],
            increasing_line_color='#10b981', 
            decreasing_line_color='#ef4444'
        )])
        
        # Récupération des jours où il n'y a pas de données pour éviter les trous
        dt_all = pd.date_range(start=df_stock['Datetime'].iloc[0], end=df_stock['Datetime'].iloc[-1], freq='1h')
        dt_obs = [d.strftime("%Y-%m-%d %H:%M:%S") for d in pd.to_datetime(df_stock['Datetime'])]
        dt_breaks = [d for d in dt_all.strftime("%Y-%m-%d %H:%M:%S").tolist() if not d in dt_obs]

        fig_stock.update_layout(
            template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,24,39,0.6)",
            height=320, margin=dict(t=10, l=5, r=5, b=10), dragmode=False,
            xaxis=dict(
                fixedrange=True, 
                title="", 
                showgrid=False, 
                rangeslider=dict(visible=False),
                # MÊME FORMAT QUE LES PORTEFEUILLES
                tickformat="%b %d, %Y<br>%H:%M",
                rangebreaks=[dict(values=dt_breaks)]
            ),
            yaxis=dict(
                fixedrange=True, 
                title="Prix", 
                gridcolor="rgba(255,255,255,0.06)",
                # AJUSTEMENT DYNAMIQUE DU MIN ET MAX
                range=[y_min, y_max] 
            )
        )
        st.plotly_chart(fig_stock, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False})
    else:
        st.warning(f"Impossible de récupérer l'historique horaire pour {vue_choisie}.")

st.divider()

# --- 5. COCKPIT D'INSPECTION ---
st.markdown("### 🔬 Cockpit d'Inspection")
bot_keys = list(df_recap["bot_id"])
selected_bot_id = st.radio("Agent :", options=bot_keys, format_func=lambda x: f"{BOTS[x]['icon']} {BOTS[x]['name']}", horizontal=True, label_visibility="collapsed")

bot_row = df_recap[df_recap["bot_id"] == selected_bot_id].iloc[0]
portfolio = raw_portfolios[selected_bot_id]
df_trades = raw_trades.get(selected_bot_id)
logs = raw_logs.get(selected_bot_id, [])

gain_brut = bot_row["gain_net"] + bot_row["frais"]
sign_net = "+" if bot_row["gain_net"] >= 0 else ""
sign_brut = "+" if gain_brut >= 0 else ""
c_net = "pos-green" if bot_row["gain_net"] >= 0 else "neg-red"

st.markdown(f"""
<div class="kpi-grid">
    <div class="kpi-box"><div class="kpi-label">💎 Valeur Nette</div><div class="kpi-num">{bot_row['val']:.2f} $</div><div style="font-size:0.78rem;" class="{c_net}">{sign_net}{bot_row['gain_net']:.2f} $</div></div>
    <div class="kpi-box"><div class="kpi-label">💵 Cash Disponible</div><div class="kpi-num">{bot_row['cash_cad']:.2f} $</div><div style="font-size:0.78rem; color:#94a3b8;">{bot_row['cash_pct']:.1f}% du portef.</div></div>
    <div class="kpi-box"><div class="kpi-label">📈 Gain Brut Marché</div><div class="kpi-num">{sign_brut}{gain_brut:.2f} $</div><div style="font-size:0.78rem; color:#94a3b8;">Avant frais</div></div>
    <div class="kpi-box"><div class="kpi-label">🏦 Frais Wealthsimple</div><div class="kpi-num neg-red">-{bot_row['frais']:.2f} $</div><div style="font-size:0.78rem; color:#94a3b8;">{bot_row['trades']} ordres</div></div>
</div>
""", unsafe_allow_html=True)

tab_logs, tab_port, tab_trades = st.tabs(["🧠 Débats IA", "💼 Positions (Live)", "📜 Ordres"])

with tab_logs:
    if logs:
        for idx_log, entry in enumerate(reversed(logs)):
            act = entry.get("action", "HOLD")
            tkr = entry.get("ticker", "AUCUN")
            dt = to_qc_time(entry.get("date", ""))
            icone = "🟢" if act == "BUY" else ("🔴" if act == "SELL" else "⏸️")
            with st.expander(f"{icone} {dt} — {act} ({tkr})", expanded=(idx_log == 0)):
                st.markdown(f"{format_badge(f'{act} {tkr}')} &nbsp; <span style='font-size:0.78rem; color:#94a3b8;'>Modèle: <code>{entry.get('model', 'N/A')}</code></span>", unsafe_allow_html=True)
                st.markdown(f"**🎯 Synthèse :** *{entry.get('synthese', '-')}*")
                st.markdown(f"**💡 Raison :** {entry.get('reasoning', '-')}")
                experts = entry.get("experts", {})
                st.markdown(f"""
                <div style="margin-top:10px;">
                    <div class="expert-box exp-op"><b>🛠️ L'Opérateur :</b><br>{experts.get('operateur', '-')}</div>
                    <div class="expert-box exp-sc"><b>⚖️ Le Sceptique :</b><br>{experts.get('sceptique', '-')}</div>
                    <div class="expert-box exp-vi"><b>🔭 Le Visionnaire :</b><br>{experts.get('visionnaire', '-')}</div>
                </div>
                """, unsafe_allow_html=True)
    else: st.info("Aucun log IA.")

with tab_port:
    donnees_rep = [{"Actif": "💵 Cash CAD", "Valeur_CAD": bot_row["cash_cad"]}]
    cartes_positions_html = ""
    for ticker, pos in portfolio.get("positions", {}).items():
        shares, cost_cad = float(pos["shares"]), float(pos["total_cost_cad"])
        is_us = not ticker.endswith(".TO")
        if ticker in live_prices: val_now_cad = (shares * live_prices[ticker] * live_usd_to_cad) if is_us else (shares * live_prices[ticker])
        else: val_now_cad = cost_cad
            
        pnl_cad = val_now_cad - cost_cad
        pnl_pct = (pnl_cad / cost_cad) * 100.0 if cost_cad > 0 else 0.0
        c_pos = "pos-green" if pnl_cad >= 0 else "neg-red"
        s_pos = "+" if pnl_cad >= 0 else ""
        donnees_rep.append({"Actif": ticker, "Valeur_CAD": val_now_cad})

        cartes_positions_html += f"""
        <div class="rank-card">
            <div><div class="rank-name">{ticker}</div><div class="rank-meta">{shares:.4f} actions • Coût: {cost_cad:.2f} $</div></div>
            <div class="rank-right"><div class="rank-val">{val_now_cad:.2f} $</div><div style="font-size:0.80rem;" class="{c_pos}">{s_pos}{pnl_cad:.2f} $ ({s_pos}{pnl_pct:.2f}%)</div></div>
        </div>
        """
    fig_tree = px.treemap(pd.DataFrame(donnees_rep), path=["Actif"], values="Valeur_CAD", color="Actif")
    fig_tree.update_traces(textinfo="label+percent root+value")
    fig_tree.update_layout(margin=dict(t=10, l=0, r=0, b=10), height=250, paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig_tree, use_container_width=True, config={"displayModeBar": False})
    if portfolio.get("positions"): st.markdown(cartes_positions_html, unsafe_allow_html=True)

with tab_trades:
    if df_trades is not None and not df_trades.empty:
        for _, tr in df_trades.iloc[::-1].iterrows():
            tr_date = to_qc_time(str(tr["Date"]))
            st.markdown(f"""
            <div class="rank-card" style="display:block;">
                <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
                    <div>{format_badge(f'{tr["Action"]} {tr["Ticker"]}')} <span style="font-size:0.75rem; color:#94a3b8;">{tr_date}</span></div>
                    <div style="font-size:0.82rem; font-weight:700; color:#f8fafc;">Prix: {tr["Price"]:.2f}$ &nbsp;|&nbsp; Frais: -{tr["Fee_CAD"]:.2f}$</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
    else: st.info("Aucune transaction.")
