import streamlit as st
import pandas as pd
import json
import os
import plotly.express as px

# Configuration de la page pour mobile
st.set_page_config(page_title="IA Trading", layout="centered")
st.title("📈 Mon Agent de Trading-QUO")

DATA_DIR = "trading_agent_data"
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")
LOG_FILE = os.path.join(DATA_DIR, "trades.csv")

CAPITAL_INITIAL = 1000.0

if os.path.exists(PORTFOLIO_FILE):
    with open(PORTFOLIO_FILE, "r") as f:
        portfolio = json.load(f)
    
    # 1. Calcul des Frais totaux à partir de l'historique CSV
    frais_totaux = 0.0
    df_trades = None
    if os.path.exists(LOG_FILE):
        df_trades = pd.read_csv(LOG_FILE)
        frais_totaux = df_trades['Fee_CAD'].sum()

    # 2. Récupération de la Valeur Totale (Liquidités + Actions)
    if portfolio.get("history_valuation") and len(portfolio["history_valuation"]) > 0:
        valeur_actuelle = portfolio["history_valuation"][-1]["total_value_cad"]
    else:
        valeur_actuelle = portfolio["cash_cad"]
        
    # 3. Calcul du Gain/Perte Brut et Net
    gain_net = valeur_actuelle - CAPITAL_INITIAL
    gain_brut = gain_net + frais_totaux

    # --- SECTION BILAN FINANCIER ---
    st.subheader("Bilan financier")
    
    # Affichage en 3 colonnes pour le mobile
    col1, col2, col3 = st.columns(3)
    col1.metric("Capital Initial", f"{CAPITAL_INITIAL:.2f} $")
    col2.metric("Frais (Fees)", f"- {frais_totaux:.2f} $")
    col3.metric("Valeur Nette", f"{valeur_actuelle:.2f} $", delta=f"{gain_net:.2f} $")

    # Affichage de la formule exacte demandée
    symbole_gain = "+" if gain_brut >= 0 else ""
    st.markdown(f"**Calcul :** {CAPITAL_INITIAL:.2f} $ (Initial) {symbole_gain} {gain_brut:.2f} $ (Gain du marché) - {frais_totaux:.2f} $ (Frais) = **{valeur_actuelle:.2f} $**")
    st.divider()

    # --- SECTION LIQUIDITÉS ET GRAPHIQUES ---
    st.metric(label="Liquidités dispo pour achat", value=f"{portfolio['cash_cad']:.2f} $ CAD")
    
    # Graphique de l'évolution
    if portfolio.get("history_valuation"):
        st.subheader("Évolution du capital")
        df_val = pd.DataFrame(portfolio["history_valuation"])
        df_val['date'] = pd.to_datetime(df_val['date'])
        st.line_chart(df_val.set_index('date')['total_value_cad'])
    
    # Treemap (Répartition)
    st.subheader("Répartition du portefeuille")
    donnees_repartition = [{"Actif": "Liquidités (Cash)", "Valeur_CAD": portfolio["cash_cad"]}]
    
    if portfolio["positions"]:
        for ticker, pos in portfolio["positions"].items():
            donnees_repartition.append({
                "Actif": ticker,
                "Valeur_CAD": pos["total_cost_cad"]
            })
            
    df_rep = pd.DataFrame(donnees_repartition)
    fig = px.treemap(df_rep, path=['Actif'], values='Valeur_CAD', color='Actif')
    fig.update_traces(textinfo="label+percent root+value")
    fig.update_layout(margin=dict(t=10, l=10, r=10, b=10))
    st.plotly_chart(fig, use_container_width=True)

    # Tableau détaillé
    if portfolio["positions"]:
        with st.expander("Voir le détail des positions"):
            df_pos = pd.DataFrame.from_dict(portfolio["positions"], orient="index")
            df_pos = df_pos.rename(columns={"shares": "Actions", "total_cost_cad": "Coût Total (CAD)", "avg_price_cad": "Prix Moyen (CAD)"})
            st.dataframe(df_pos)
            
else:
    st.warning("En attente de la première exécution du robot.")

# --- HISTORIQUE DES TRANSACTIONS ---
st.subheader("Derniers mouvements")
if df_trades is not None:
    st.dataframe(df_trades.iloc[::-1], use_container_width=True)
else:
    st.info("Aucune transaction effectuée pour le moment (HOLD).")
