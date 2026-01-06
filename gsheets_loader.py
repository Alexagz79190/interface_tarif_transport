import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

@st.cache_data(show_spinner=False)
def load_sheet(spreadsheet_id, tab_name):
    creds_dict = st.secrets["gcp_service_account"]
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(creds)

    sh = client.open_by_key(spreadsheet_id)

    # ✅ STOP si onglet introuvable
    try:
        ws = sh.worksheet(tab_name)
    except Exception as e:
        raise ValueError(f"❌ Onglet '{tab_name}' introuvable dans le fichier {spreadsheet_id}. Onglets dispo: {[w.title for w in sh.worksheets()]}")

    data = ws.get_all_values()
    return pd.DataFrame(data)

print(f"✅ Onglet chargé: {ws.title} | nb lignes: {len(data)} | nb colonnes: {len(data[0]) if data else 0}")

