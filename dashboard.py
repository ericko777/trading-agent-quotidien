import streamlit as st
import pandas as pd
import json
import os
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go

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

# --- CSS SUR MESURE POUR ÉCRAN AMOLED GALAXY S24+ (19.5:9) ---
st.markdown("""
<style>
    /* Dégagement de la barre supérieure Streamlit */
    header[data-testid="stHeader"] {
        background: transparent !important;
        height: 2.5rem !important;
    }

    /* Marge supérieure aérée pour mobile S24+ */
    .block-container {
        padding-top: 4.2rem !important; /* Dégage complètement le titre sous la barre */
        padding-bottom: 3rem !important;
        padding-left: 0.9rem !important;
        padding-right: 0.9rem !important;
        max-width: 520px !important;
    }

    /* Carte En-tête Globale */
    .hero-card {
        background: linear-gradient(145deg, #0f172a 0%, #1e293b 100%);
        border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 18px;
        padding: 18px;
        margin-top: 0.5rem;
        margin-bottom: 16px;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    }
    .hero-title {
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 1.2px;
        color: #94a3b8;
        margin-bottom: 4px;
        font-weight: 600;
    }
    .hero-value {
        font-size: 2.0rem;
        font-weight: 800;
        color: #f8fafc;
        line-height: 1.15;
    }
    .hero-sub {
        font-size: 0.88rem;
        margin-top: 6px;
        font-weight: 600;
    }
    /* Grille 2x2 anti-troncature pour S24+ */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 10px;
        margin-top: 12px;
        margin-bottom: 14px;
    }
    .kpi-box {
        background: #111827;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 14px;
        padding: 12px 14px;
    }
    .kpi-label {
        font-size: 0.72rem;
        color: #9ca3af;
        text-transform: uppercase;
        letter-spacing: 0.6px;
        margin-bottom: 4px;
    }
    .kpi-num {
        font-size: 1.18rem;
        font-weight: 700;
        color: #f3f4f6;
    }
    /* Cartes de Classement (Leaderboard) */
    .rank-card {
        background: #111827;
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 14px;
        padding: 12px 14px;
        margin-bottom: 8px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .rank-left {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .rank-medal {
        font-size: 1.35rem;
        min-width: 28px;
        text-align: center;
    }
    .rank-name {
        font-weight: 700;
        font-size: 0.95rem;
        color: #f8fafc;
    }
    .rank-meta {
        font-size: 0.74rem;
        color: #94a3b8;
    }
    .rank-right {
        text-align: right;
    }
    .rank-val {
        font-weight: 800;
        font-size: 1.02rem;
        color: #f8fafc;
    }
    /* Badges d'actions et P&L */
    .pos-green { color: #10b981 !important; font-weight: 700; }
    .neg-red { color: #ef4444 !important; font-weight: 700; }
    .neutral-grey { color: #94a3b8 !important; font-weight: 600; }
    
    .badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 99px;
        font-size: 0.70rem;
        font-weight: 700;
        letter-spacing: 0.4px;
    }
    .badge-buy { background: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }
    .badge-sell { background: rgba(239, 68, 68, 0.18); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }
    .badge-hold { background: rgba(148, 163, 184, 0.15); color: #cbd5e1; border: 1px solid rgba(148, 163, 184, 0.3); }

    /* Formule équation Wealthsimple */
    .equation-bar {
        background: rgba(30, 41, 59, 0.7);
        border-left: 4px solid #3b82f6;
        border-radius: 10px;
        padding: 10px 12px;
        font-size: 0.82rem;
        color: #e2e8f0;
        margin-bottom: 14px;
    }
    /* Bulles d'experts */
    .expert-box {
        border-radius: 12px;
        padding: 11px 13px;
        margin-bottom: 8px;
        font-size: 0.85rem;
        line-height: 1.45;
    }
    .exp-op { background: rgba(59, 130, 246, 0.12); border-left: 3px solid #3b82f6; color: #dbeafe; }
    .exp-sc { background: rgba(245, 158, 11, 0.12); border-left: 3px solid #f59e0b; color: #fef3c7; }
    .exp-vi { background: rgba(16, 185, 129, 0.12); border-left: 3px solid #10b981; color: #d1fae5; }
</style>
""", unsafe_allow_html=True)

# --- FONCTION DE PRIX EN DIRECT (MISE EN CACHE 5 MIN POUR RAPIDITÉ MOBILE) ---
@st.cache_data(ttl=300, show_spinner=False)
def get_live_prices(tickers_tuple):
    """Récupère les prix actuels et le taux USD/CAD pour valoriser les positions ouvertes."""
    prices = {}
    usd_to_cad = 1.38
    try:
        fx = yf.Ticker("CADUSD=X").history(period="5d")
        if not fx.empty:
            usd_to_cad = float(1.0 / fx["Close"].iloc[-1])
    except Exception:
        pass

    for t in tickers_tuple:
        try:
            h = yf.Ticker(t).history(period="5d")
            if not h.empty:
                prices[t] = float(h["Close"].iloc[-1])
        except Exception:
            pass
    return prices, usd_to_cad

def format_badge(action_str):
    if "BUY" in action_str:
        return f'<span class="badge badge-buy">🟢 {action_str}</span>'
    elif "SELL" in action_str:
        return f'<span class="badge badge-sell">🔴 {action_str}</span>'
    return f'<span class="badge badge-hold">⏸️ {action_str}</span>'

# --- 1. COLLECTE DES DONNÉES DES 5 BOTS ---
recap_list = []
courbes_list = []
all_open_tickers = set()
raw_portfolios = {}
raw_trades = {}
raw_logs = {}

for bot_id, info in BOTS.items():
    p_file = os.path.join(DATA_DIR, f"portfolio_{bot_id}.json")
    t_file = os.path.join(DATA_DIR, f"trades_{bot_id}.csv")
    l_file = os.path.join(DATA_DIR, f"logs_{bot_id}.json")

    if os.path.exists(p_file):
        with open(p_file, "r", encoding="utf-8") as f:
            p_data = json.load(f)
        raw_portfolios[bot_id] = p_data
        for sym in p_data.get("positions", {}).keys():
            all_open_tickers.add(sym)

        frais = 0.0
        nb_trades = 0
        if os.path.exists(t_file):
            df_t = pd.read_csv(t_file)
            raw_trades[bot_id] = df_t
            frais = float(df_t["Fee_CAD"].sum())
            nb_trades = len(df_t)

        nb_requetes = 0
        derniere_action = "HOLD"
        dernier_ticker = "-"
        derniere_date = "Aucune"
        if os.path.exists(l_file):
            with open(l_file, "r", encoding="utf-8") as f:
                l_data = json.load(f)
            raw_logs[bot_id] = l_data
            nb_requetes = len(l_data)
            if nb_requetes > 0:
                derniere_action = l_data[-1].get("action", "HOLD")
                dernier_ticker = l_data[-1].get("ticker", "-")
                derniere_date = l_data[-1].get("date", "")

        val_actuelle = float(p_data["history_valuation"][-1]["total_value_cad"]) if p_data.get("history_valuation") else float(p_data["cash_cad"])
        gain_net = val_actuelle - CAPITAL_INITIAL
        roi_pct = (gain_net / CAPITAL_INITIAL) * 100.0
        cash_pct = (float(p_data["cash_cad"]) / val_actuelle) * 100.0 if val_actuelle > 0 else 100.0

        recap_list.append({
            "bot_id": bot_id,
            "icon": info["icon"],
            "name": info["name"],
            "style": info["style"],
            "full_name": f"{info['icon']} {info['name']}",
            "val": val_actuelle,
            "gain_net": gain_net,
            "roi_pct": roi_pct,
            "frais": frais,
            "trades": nb_trades,
            "requetes": nb_requetes,
            "cash_cad": float(p_data["cash_cad"]),
            "cash_pct": cash_pct,
            "last_action": derniere_action,
            "last_ticker": dernier_ticker,
            "last_date": derniere_date
        })

        for item in p_data.get("history_valuation", []):
            courbes_list.append({
                "Date": item["date"],
                "Bot": f"{info['icon']} {info['name']}",
                "Valeur (CAD)": float(item["total_value_cad"])
            })

if not recap_list:
    st.markdown("""
    <div class="hero-card">
        <div class="hero-title">⏳ Initialisation de l'Arène</div>
        <div class="hero-value">En attente du 1er Run</div>
        <div class="hero-sub neutral-grey">Lance 'Run workflow' dans l'onglet Actions de GitHub pour réveiller tes 5 bots.</div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# Tri du classement par Valeur Totale décroissante
df_recap = pd.DataFrame(recap_list).sort_values(by="val", ascending=False).reset_index(drop=True)

# --- 2. BANDEAU "EMPIRE GLOBAL" (SOMME DES 5 PORTEFEUILLES) ---
capital_global_initial = CAPITAL_INITIAL * len(df_recap)
valeur_globale_actuelle = df_recap["val"].sum()
gain_global_net = valeur_globale_actuelle - capital_global_initial
roi_global_pct = (gain_global_net / capital_global_initial) * 100.0
frais_globaux = df_recap["frais"].sum()
trades_globaux = int(df_recap["trades"].sum())
leader = df_recap.iloc[0]
derniere_maj = df_recap["last_date"].max()

couleur_globale = "pos-green" if gain_global_net >= 0 else "neg-red"
signe_global = "+" if gain_global_net >= 0 else ""

st.markdown(f"""
<div class="hero-card">
    <div style="display:flex; justify-content:space-between; align-items:center;">
        <div class="hero-title">🏆 Fonds Global ({len(df_recap)} Bots Actifs)</div>
        <div style="font-size:0.70rem; color:#64748b;">MAJ : {derniere_maj}</div>
    </div>
    <div class="hero-value">{valeur_globale_actuelle:,.2f} $ <span style="font-size:0.95rem; font-weight:500; color:#94a3b8;">CAD</span></div>
    <div class="hero-sub {couleur_globale}">
        {signe_global}{gain_global_net:,.2f} $ ({signe_global}{roi_global_pct:.2f}%) depuis le départ ({capital_global_initial:,.0f} $)
    </div>
    <div class="kpi-grid" style="margin-bottom:0px; margin-top:14px;">
        <div class="kpi-box" style="padding:9px 12px;">
            <div class="kpi-label">👑 Leader Actuel</div>
            <div style="font-size:0.95rem; font-weight:700; color:#f8fafc;">{leader['icon']} {leader['name']}</div>
        </div>
        <div class="kpi-box" style="padding:9px 12px;">
            <div class="kpi-label">💸 Frais WS Totaux</div>
            <div style="font-size:0.95rem; font-weight:700; color:#f87171;">-{frais_globaux:.2f} $ ({trades_globaux} trades)</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# --- 3. PODIUM MOBILE-FIRST DES 5 STRATÉGIES ---
st.markdown("### 🏁 Classement en Direct")

medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
for idx, row in df_recap.iterrows():
    medal = medals[idx] if idx < len(medals) else f"#{idx+1}"
    c_class = "pos-green" if row["gain_net"] >= 0 else "neg-red"
    sign = "+" if row["gain_net"] >= 0 else ""
    act_str = f"{row['last_action']} {row['last_ticker']}" if row["last_action"] != "HOLD" else "HOLD"
    badge_html = format_badge(act_str)
    invested_pct = 100.0 - row["cash_pct"]

    st.markdown(f"""
    <div class="rank-card">
        <div class="rank-left">
            <div class="rank-medal">{medal}</div>
            <div>
                <div class="rank-name">{row['icon']} {row['name']}</div>
                <div class="rank-meta">{row['style']} • Investi: {invested_pct:.0f}% • Frais: -{row['frais']:.2f}$</div>
            </div>
        </div>
        <div class="rank-right">
            <div class="rank-val">{row['val']:.2f} $</div>
            <div style="font-size:0.78rem;" class="{c_class}">{sign}{row['gain_net']:.2f}$ ({sign}{row['roi_pct']:.2f}%)</div>
            <div style="margin-top:3px;">{badge_html}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# --- 4. GRAPHIQUE DE LA COURSE (VERROUILLÉ POUR LE POUCE SUR S24+) ---
if courbes_list:
    df_courbes = pd.DataFrame(courbes_list)
    fig_comp = px.line(
        df_courbes,
        x="Date",
        y="Valeur (CAD)",
        color="Bot",
        markers=True
    )
    # Ligne de seuil de rentabilité (1000 $)
    fig_comp.add_hline(
        y=CAPITAL_INITIAL,
        line_dash="dot",
        line_color="rgba(255,255,255,0.35)",
        annotation_text="Départ 1000$",
        annotation_position="bottom right"
    )
    fig_comp.update_layout(
        title=dict(text="📈 Course des Portefeuilles", font=dict(size=15)),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(17,24,39,0.6)",
        height=320,
        margin=dict(t=40, l=5, r=5, b=10),
        dragmode=False,
        xaxis=dict(fixedrange=True, title="", showgrid=False),
        yaxis=dict(fixedrange=True, title="CAD ($)", gridcolor="rgba(255,255,255,0.06)"),
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5, title="")
    )
    st.plotly_chart(fig_comp, use_container_width=True, config={"displayModeBar": False, "scrollZoom": False})

st.divider()

# --- 5. SÉLECTEUR TACTILE D'INSPECTION D'UN BOT ---
st.markdown("### 🔬 Cockpit d'Inspection")

bot_keys = list(df_recap["bot_id"])
selected_bot_id = st.radio(
    "Sélectionne un agent :",
    options=bot_keys,
    format_func=lambda x: f"{BOTS[x]['icon']} {BOTS[x]['name']}",
    horizontal=True,
    label_visibility="collapsed"
)

bot_row = df_recap[df_recap["bot_id"] == selected_bot_id].iloc[0]
portfolio = raw_portfolios[selected_bot_id]
df_trades = raw_trades.get(selected_bot_id)
logs = raw_logs.get(selected_bot_id, [])

gain_brut = bot_row["gain_net"] + bot_row["frais"]
sign_net = "+" if bot_row["gain_net"] >= 0 else ""
sign_brut = "+" if gain_brut >= 0 else ""
c_net = "pos-green" if bot_row["gain_net"] >= 0 else "neg-red"

# Grille 2x2 de métriques financières pour le bot sélectionné
st.markdown(f"""
<div class="kpi-grid">
    <div class="kpi-box">
        <div class="kpi-label">💎 Valeur Nette</div>
        <div class="kpi-num">{bot_row['val']:.2f} $</div>
        <div style="font-size:0.78rem;" class="{c_net}">{sign_net}{bot_row['gain_net']:.2f} $ ({sign_net}{bot_row['roi_pct']:.2f}%)</div>
    </div>
    <div class="kpi-box">
        <div class="kpi-label">💵 Cash Disponible</div>
        <div class="kpi-num">{bot_row['cash_cad']:.2f} $</div>
        <div style="font-size:0.78rem; color:#94a3b8;">{bot_row['cash_pct']:.1f}% du portefeuille</div>
    </div>
    <div class="kpi-box">
        <div class="kpi-label">📈 Gain Brut Marché</div>
        <div class="kpi-num">{sign_brut}{gain_brut:.2f} $</div>
        <div style="font-size:0.78rem; color:#94a3b8;">Avant frais de courtage</div>
    </div>
    <div class="kpi-box">
        <div class="kpi-label">🏦 Frais Wealthsimple</div>
        <div class="kpi-num neg-red">-{bot_row['frais']:.2f} $</div>
        <div style="font-size:0.78rem; color:#94a3b8;">{bot_row['trades']} ordres | {bot_row['requetes']} analyses</div>
    </div>
</div>
<div class="equation-bar">
    <b>Bilan réel :</b> {CAPITAL_INITIAL:.2f}$(Initial) {sign_brut} {gain_brut:.2f}$ (Marché) - {bot_row['frais']:.2f}$(Frais FX) = <b>{bot_row['val']:.2f}$ CAD</b>
</div>
""", unsafe_allow_html=True)

# --- 6. LES 4 ONGLETS D'ANALYSE APPROFONDIE ---
tab_logs, tab_port, tab_trades, tab_prompt = st.tabs([
    "🧠 Débats IA",
    "💼 Positions",
    "📜 Ordres",
    "📄 Règles .txt"
])

# ONGLET 1 : JOURNAL DES REQUÊTES IA (DÉBATS D'EXPERTS)
with tab_logs:
    if logs:
        st.caption(f"{len(logs)} analyses enregistrées pour **{BOTS[selected_bot_id]['name']}** (de la plus récente à la plus ancienne).")
        for idx_log, entry in enumerate(reversed(logs)):
            act = entry.get("action", "HOLD")
            tkr = entry.get("ticker", "AUCUN")
            dt = entry.get("date", "")
            nb_t = entry.get("tickers_analyzed_count", 0)
            icone = "🟢" if act == "BUY" else ("🔴" if act == "SELL" else "⏸️")

            # Le dernier log est ouvert par défaut pour une lecture immédiate sur mobile !
            with st.expander(f"{icone} {dt} — {act} ({tkr})", expanded=(idx_log == 0)):
                st.markdown(
                    f"{format_badge(f'{act} {tkr}')} &nbsp; "
                    f"<span style='font-size:0.78rem; color:#94a3b8;'>Modèle : <code>{entry.get('model', 'N/A')}</code> • {nb_t} titres scrutés</span>",
                    unsafe_allow_html=True
                )
                if act in ["BUY", "SELL"]:
                    exec_ok = entry.get("order_executed", False)
                    statut_txt = "✅ Exécuté" if exec_ok else "⚠️ Rejeté (fonds/position insuffisants)"
                    st.markdown(f"**Montant engagé :** `{entry.get('amount_cad', 0):.2f} $ CAD` — {statut_txt}")

                st.markdown(f"**🎯 Synthèse du Comité :** *{entry.get('synthese', 'Non spécifiée')}*")
                st.markdown(f"**💡 Décision Finale :** {entry.get('reasoning', 'Non spécifiée')}")

                experts = entry.get("experts", {})
                st.markdown(f"""
                <div style="margin-top:10px;">
                    <div class="expert-box exp-op"><b>🛠️ L'Opérateur (Exécution & Frais)</b><br>{experts.get('operateur', '-')}</div>
                    <div class="expert-box exp-sc"><b>⚖️ Le Sceptique (Avocat du Diable)</b><br>{experts.get('sceptique', '-')}</div>
                    <div class="expert-box exp-vi"><b>🔭 Le Visionnaire (Opportunités)</b><br>{experts.get('visionnaire', '-')}</div>
                </div>
                """, unsafe_allow_html=True)

                tickers_list = entry.get("tickers_analyzed", [])
                if tickers_list:
                    st.caption(f"Titres analysés : {', '.join(tickers_list)}")
    else:
        st.info("Aucune requête IA enregistrée pour ce bot.")

# ONGLET 2 : PORTEFEUILLE & VALORISATION EN DIRECT DES POSITIONS
with tab_port:
    positions = portfolio.get("positions", {})
    live_prices, live_usd_to_cad = get_live_prices(tuple(all_open_tickers)) if all_open_tickers else ({}, 1.38)

    donnees_rep = [{"Actif": "💵 Cash CAD", "Valeur_CAD": round(float(portfolio["cash_cad"]), 2)}]
    cartes_positions_html = ""

    for ticker, pos in positions.items():
        shares = float(pos["shares"])
        cost_cad = float(pos["total_cost_cad"])
        avg_cost_cad = float(pos.get("avg_price_cad", cost_cad / shares if shares > 0 else 0))
        is_us = not ticker.endswith(".TO")

        # Calcul de la vraie valeur marchande actuelle
        if ticker in live_prices:
            px_now = live_prices[ticker]
            val_now_cad = (shares * px_now * live_usd_to_cad) if is_us else (shares * px_now)
        else:
            px_now = avg_cost_cad
            val_now_cad = cost_cad

        pnl_cad = val_now_cad - cost_cad
        pnl_pct = (pnl_cad / cost_cad) * 100.0 if cost_cad > 0 else 0.0
        c_pos = "pos-green" if pnl_cad >= 0 else "neg-red"
        s_pos = "+" if pnl_cad >= 0 else ""
        devise_lbl = "USD" if is_us else "CAD"

        donnees_rep.append({"Actif": ticker, "Valeur_CAD": round(val_now_cad, 2)})

        cartes_positions_html += f"""
        <div class="rank-card">
            <div>
                <div class="rank-name">{ticker} <span style="font-size:0.72rem; color:#94a3b8;">({devise_lbl})</span></div>
                <div class="rank-meta">{shares:.4f} actions • Coût initial : {cost_cad:.2f} $</div>
            </div>
            <div class="rank-right">
                <div class="rank-val">{val_now_cad:.2f} $ CAD</div>
                <div style="font-size:0.80rem;" class="{c_pos}">{s_pos}{pnl_cad:.2f} $ ({s_pos}{pnl_pct:.2f}%)</div>
            </div>
        </div>
        """

    df_rep = pd.DataFrame(donnees_rep)
    fig_tree = px.treemap(
        df_rep,
        path=["Actif"],
        values="Valeur_CAD",
        color="Actif",
        color_discrete_sequence=px.colors.qualitative.Bold
    )
    fig_tree.update_traces(textinfo="label+percent root+value", textfont=dict(size=14))
    fig_tree.update_layout(
        margin=dict(t=10, l=0, r=0, b=10),
        height=250,
        paper_bgcolor="rgba(0,0,0,0)"
    )
    st.plotly_chart(fig_tree, use_container_width=True, config={"displayModeBar": False})

    if positions:
        st.markdown("#### 📌 Détail des Lignes Ouvertes (P&L Temps Réel)")
        st.markdown(cartes_positions_html, unsafe_allow_html=True)
    else:
        st.info("100 % en Liquidités (Aucune action détenue actuellement).")

# ONGLET 3 : HISTORIQUE DES TRANSACTIONS (BUY / SELL)
with tab_trades:
    if df_trades is not None and not df_trades.empty:
        st.caption(f"{len(df_trades)} transactions exécutées par ce bot.")
        for _, tr in df_trades.iloc[::-1].iterrows():
            t_act = str(tr["Action"])
            t_sym = str(tr["Ticker"])
            t_sh = float(tr["Shares"])
            t_px = float(tr["Price"])
            t_fee = float(tr["Fee_CAD"])
            t_cash = float(tr["Cash_CAD_Left"])
            t_dt = str(tr["Date"])
            t_rsn = str(tr.get("Reason", ""))

            st.markdown(f"""
            <div class="rank-card" style="display:block;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <div>{format_badge(f'{t_act} {t_sym}')} <span style="font-size:0.75rem; color:#94a3b8; margin-left:6px;">{t_dt}</span></div>
                    <div style="font-size:0.82rem; font-weight:700; color:#f8fafc;">Prix : {t_px:.2f}$ &nbsp;|&nbsp; Frais : -{t_fee:.2f}$</div>
                </div>
                <div style="font-size:0.78rem; color:#cbd5e1;">
                    <b>Quantité :</b> {t_sh:.4f} actions • <b>Cash restant :</b> {t_cash:.2f} $ CAD
                </div>
                <div style="font-size:0.76rem; color:#94a3b8; margin-top:4px; font-style:italic;">
                    "{t_rsn}"
                </div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("Aucun ordre BUY ou SELL exécuté pour le moment.")

# ONGLET 4 : LECTURE DU FICHIER .TXT DE STRATÉGIE
with tab_prompt:
    prompt_path = os.path.join(PROMPTS_DIR, BOTS[selected_bot_id]["prompt"])
    st.caption(f"Fichier source : `prompts/{BOTS[selected_bot_id]['prompt']}`")
    if os.path.exists(prompt_path):
        with open(prompt_path, "r", encoding="utf-8") as f:
            st.code(f.read(), language="markdown")
    else:
        st.warning(f"Le fichier `{prompt_path}` n'a pas encore été trouvé dans le dépôt.")
