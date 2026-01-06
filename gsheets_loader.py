import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials

@st.cache_data(show_spinner=False)
def load_sheet(spreadsheet_id: str, tab_name: str) -> pd.DataFrame:
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes
    )

    client = gspread.authorize(creds)
    sh = client.open_by_key(spreadsheet_id)
    ws = sh.worksheet(tab_name)

    values = ws.get_all_values()
    df = pd.DataFrame(values)

    return df
