import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

@st.cache_data(show_spinner=False)
def load_sheet(spreadsheet_id, tab_name):
    creds_dict = st.secrets["gcp_service_account"]
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    sh = client.open_by_key(spreadsheet_id)

    # Debug: liste des onglets disponibles
    titles = [w.title for w in sh.worksheets()]
    print("📄 Onglets dispo:", titles)

    # ✅ STRICT : si onglet introuvable -> erreur
    try:
        ws = sh.worksheet(tab_name)
    except Exception:
        raise ValueError(
            f"❌ Onglet '{tab_name}' introuvable dans le fichier {spreadsheet_id}. "
            f"Onglets dispo: {titles}"
        )

    data = ws.get_all_values()

    # ✅ Debug : onglet réellement chargé
    nb_lignes = len(data)
    nb_cols = len(data[0]) if data and len(data) > 0 else 0
    print(f"✅ Onglet chargé: {ws.title} | nb lignes: {nb_lignes} | nb colonnes: {nb_cols}")

    return pd.DataFrame(data)


