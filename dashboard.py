import streamlit as st
import pandas as pd
import json
import os
import plotly.express as px

st.set_page_config(page_title="Arène IA Trading", layout="centered")
st.title("🏆 Arène des 5 Bots de Trading")

DATA_DIR = "trading_agent_data"
CAPITAL_INITIAL = 1000.0

BOTS = {
    "momentum": "🔥 Trend Follower (Momentum)",
    "value": "🏛️ Value Compounder (Buffett)",
    "quant": "⚡ Mean Reverter (Quant)",
    "growth": "🚀 Growth Breakout (Tech)",
    "macro": "🌍 Macro Sentiment (Dalio)"
}

# --- 1. COLLECTE DES DONNÉES GLOBALES POUR LE CLASSEMENT ---
recap_list = []
courbes_list = []

for bot_id, bot_name in BOTS.items():
    p_file = os.path.join(DATA_DIR, f"portfolio_{bot_id}.json")
    t_file = os.path.join(DATA_DIR, f"trades_{bot_id}.csv")
    l_file = os.path.join(DATA_DIR, f"logs_{bot_id}.json")

    if os.path.exists(p_file):
        with open(p_file, "r", encoding="utf-8") as f:
            p_data = json.load(f)
        
        frais = 0.0
        nb_trades = 0
        if os.path.exists(t_file):
            df_t = pd.read_csv(t_file)
            frais = df_t["Fee_CAD"].sum()
            nb_trades = len(df_t)

        nb_requetes = 0
        derniere_action = "En attente"
        if os.path.exists(l_file):
            with open(l_file, "r", encoding="utf-8") as f:
                l_data = json.load(f)
                nb_requetes = len(l_data)
                if nb_requetes > 0:
                    derniere_action = f"{l_data[-1]['action']} ({l_data[-1]['ticker']})"

        val_actuelle = p_data["history_valuation"][-1]["total_value_cad"] if p_data.get("history_valuation") else p_data["cash_cad"]
        gain_net = val_actuelle - CAPITAL_INITIAL

        recap_list.append({
            "Stratégie": bot_name,
            "Valeur Totale": round(val_actuelle, 2),
            "Gain Net ($)": round(gain_net, 2),
            "Frais Payés ($)": round(frais, 2),
            "Trades": nb_trades,
            "Requêtes IA": nb_requetes,
            "Dernier Choix": derniere_action
        })

        for item in p_data.get("history_valuation", []):
            courbes_list.append({
                "Date": item["date"],
                "Stratégie": bot_name,
                "Valeur (CAD)": item["total_value_cad"]
            })

if not recap_list:
    st.warning("Aucune donnée trouvée. Lance une première exécution ('Run workflow') dans l'onglet Actions de GitHub !")
    st.stop()

# --- 2. AFFICHAGE DU CLASSEMENT GÉNÉRAL ---
st.subheader("Classement en direct")
df_recap = pd.DataFrame(recap_list).sort_values(by="Valeur Totale", ascending=False)
st.dataframe(df_recap, use_container_width=True, hide_index=True)

if courbes_list:
    df_courbes = pd.DataFrame(courbes_list)
    fig_comp = px.line(df_courbes, x="Date", y="Valeur (CAD)", color="Stratégie", markers=True, title="Course des portefeuilles (Base 1000 $)")
    fig_comp.update_layout(legend=dict(orientation="h", yanchor="bottom", y=-0.5, xanchor="center", x=0.5))
    st.plotly_chart(fig_comp, use_container_width=True)

st.divider()

# --- 3. INSPECTION DÉTAILLÉE D'UN BOT ET DE SES LOGS IA ---
st.subheader("🔍 Inspecter le cerveau et le portefeuille d'un Bot")
selected_bot_id = st.selectbox("Choisis l'agent à analyser :", options=list(BOTS.keys()), format_func=lambda x: BOTS[x])

p_file = os.path.join(DATA_DIR, f"portfolio_{selected_bot_id}.json")
t_file = os.path.join(DATA_DIR, f"trades_{selected_bot_id}.csv")
l_file = os.path.join(DATA_DIR, f"logs_{selected_bot_id}.json")

if os.path.exists(p_file):
    with open(p_file, "r", encoding="utf-8") as f:
        portfolio = json.load(f)

    frais_totaux = 0.0
    df_trades = None
    if os.path.exists(t_file):
        df_trades = pd.read_csv(t_file)
        frais_totaux = df_trades["Fee_CAD"].sum()

    valeur_actuelle = portfolio["history_valuation"][-1]["total_value_cad"] if portfolio.get("history_valuation") else portfolio["cash_cad"]
    gain_net = valeur_actuelle - CAPITAL_INITIAL
    gain_brut = gain_net + frais_totaux

    col1, col2, col3 = st.columns(3)
    col1.metric("Capital Initial", f"{CAPITAL_INITIAL:.2f} $")
    col2.metric("Frais (Fees)", f"- {frais_totaux:.2f} $")
    col3.metric("Valeur Nette", f"{valeur_actuelle:.2f} $", delta=f"{gain_net:.2f} $")

    symbole_gain = "+" if gain_brut >= 0 else ""
    st.markdown(f"**Équation :** {CAPITAL_INITIAL:.2f} $(Initial) {symbole_gain} {gain_brut:.2f}$ (Gain marché) - {frais_totaux:.2f} $(Frais) = **{valeur_actuelle:.2f}$**")

    # Onglets internes pour séparer les Logs IA, le Portefeuille et les Transactions
    tab_logs, tab_port, tab_trades = st.tabs(["🧠 Journal des requêtes IA (Logs)", "💼 Portefeuille", "📜 Transactions (BUY/SELL)"])

    with tab_logs:
        st.caption("Voici tout ce que l'IA s'est dit lors de chaque réveil (même lorsqu'elle a décidé de faire HOLD).")
        if os.path.exists(l_file):
            with open(l_file, "r", encoding="utf-8") as f:
                logs = json.load(f)
            
            for entry in reversed(logs):
                icone = "⏸️" if entry["action"] == "HOLD" else ("🟢" if entry["action"] == "BUY" else "🔴")
                titre_log = f"{icone} {entry['date']} — Décision : {entry['action']} ({entry['ticker']}) | {entry['tickers_analyzed_count']} titres analysés"
                
                with st.expander(titre_log):
                    st.markdown(f"**Modèle utilisé :** `{entry.get('model', 'Inconnu')}`")
                    st.markdown(f"**Titres scrutés ({entry['tickers_analyzed_count']}) :** {', '.join(entry.get('tickers_analyzed', []))}")
                    if entry["action"] in ["BUY", "SELL"]:
                        statut_exec = "✅ Ordre exécuté avec succès" if entry.get("order_executed") else "⚠️ Ordre non exécuté (fonds ou position insuffisants)"
                        st.markdown(f"**Montant visé :** {entry.get('amount_cad', 0)} $ CAD ({statut_exec})")
                    
                    st.markdown("---")
                    st.markdown("#### 🗣️ Le Débat du Comité d'Experts")
                    experts = entry.get("experts", {})
                    st.info(f"**🛠️ L'Opérateur (Exécution & Frais) :**\n{experts.get('operateur', 'Non disponible')}")
                    st.warning(f"**⚖️ Le Sceptique (Risques & Avocat du diable) :**\n{experts.get('sceptique', 'Non disponible')}")
                    st.success(f"**🔭 Le Visionnaire (Opportunités & Momentum) :**\n{experts.get('visionnaire', 'Non disponible')}")
                    
                    st.markdown("#### 🎯 Synthèse et Raisonnement Final")
                    st.markdown(f"**Synthèse :** *{entry.get('synthese', '')}*")
                    st.markdown(f"**Pourquoi ce choix :** {entry.get('reasoning', '')}")
        else:
            st.info("Aucun log disponible pour le moment.")

    with tab_port:
        st.metric("Liquidités disponibles (Cash)", f"{portfolio['cash_cad']:.2f} $ CAD")
        donnees_rep = [{"Actif": "Liquidités (Cash)", "Valeur_CAD": portfolio["cash_cad"]}]
        for ticker, pos in portfolio["positions"].items():
            donnees_rep.append({"Actif": ticker, "Valeur_CAD": pos["total_cost_cad"]})
        
        df_rep = pd.DataFrame(donnees_rep)
        fig_tree = px.treemap(df_rep, path=["Actif"], values="Valeur_CAD", color="Actif")
        fig_tree.update_traces(textinfo="label+percent root+value")
        fig_tree.update_layout(margin=dict(t=10, l=10, r=10, b=10))
        st.plotly_chart(fig_tree, use_container_width=True)

        if portfolio["positions"]:
            df_pos = pd.DataFrame.from_dict(portfolio["positions"], orient="index")
            st.dataframe(df_pos, use_container_width=True)

    with tab_trades:
        if df_trades is not None and not df_trades.empty:
            st.dataframe(df_trades.iloc[::-1], use_container_width=True, hide_index=True)
        else:
            st.info("Aucune transaction d'achat ou de vente exécutée pour le moment.")
