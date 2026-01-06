import streamlit as st
import pandas as pd

from gsheets_loader import load_sheet
from pricing_engine import (
    load_geodis_from_sheet,
    load_dachser_from_sheet,
    load_kuehne_from_sheet,
    load_xpo_from_sheet,
    load_taxes_from_sheet,
    compute_prices
)

st.set_page_config(page_title="Comparateur Transport", layout="wide")

# -----------------------------------------------------------------------------
# CONFIG : IDs GOOGLE SHEETS (dans st.secrets)
# -----------------------------------------------------------------------------
# Exemple attendu dans secrets:
# GEODIS_ID=...
# GEODIS_TAB=...
# DACHSER_ID=...
# DACHSER_TAB=...
# KUEHNE_ID=...
# KUEHNE_TAB=...
# XPO_ID=...
# XPO_TAB=...
# TAXE_ID=...
# TAXE_TAB=...

def get_ids_from_secrets():
    keys = [
        "GEODIS_ID", "GEODIS_TAB",
        "DACHSER_ID", "DACHSER_TAB",
        "KUEHNE_ID", "KUEHNE_TAB",
        "XPO_ID", "XPO_TAB",
        "TAXE_ID", "TAXE_TAB",
    ]
    missing = [k for k in keys if k not in st.secrets]
    if missing:
        raise ValueError(f"Secrets manquants : {missing}")

    return {k: st.secrets[k] for k in keys}


# -----------------------------------------------------------------------------
# LOAD ALL DATA (cache)
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=True)
def load_all_data(version="v1"):
    ids = get_ids_from_secrets()

    # RAW
    df_geodis_raw  = load_sheet(ids["GEODIS_ID"],  ids["GEODIS_TAB"])
    df_dachser_raw = load_sheet(ids["DACHSER_ID"], ids["DACHSER_TAB"])
    df_kuehne_raw  = load_sheet(ids["KUEHNE_ID"],  ids["KUEHNE_TAB"])
    df_xpo_raw     = load_sheet(ids["XPO_ID"],     ids["XPO_TAB"])
    df_taxe_raw    = load_sheet(ids["TAXE_ID"],    ids["TAXE_TAB"])

    # PARSE
    df_geodis  = load_geodis_from_sheet(df_geodis_raw)
    df_dachser = load_dachser_from_sheet(df_dachser_raw)
    df_kuehne  = load_kuehne_from_sheet(df_kuehne_raw)
    df_xpo     = load_xpo_from_sheet(df_xpo_raw)
    taxes      = load_taxes_from_sheet(df_taxe_raw)

    return df_geodis, df_dachser, df_kuehne, df_xpo, taxes, ids


# -----------------------------------------------------------------------------
# INIT SESSION STATE (palettes)
# -----------------------------------------------------------------------------
if "palettes" not in st.session_state:
    st.session_state.palettes = [
        {"poids": 100.0, "L": 80.0, "l": 120.0, "H": 100.0}
    ]


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
st.title("📦 Comparateur Tarif Transport")

with st.expander("🛠️ Debug / Données chargées", expanded=True):
    try:
        # Change version si tu veux forcer le reload
        df_geodis, df_dachser, df_kuehne, df_xpo, taxes, ids = load_all_data(version="v7")

        st.write("✅ IDs / Onglets utilisés :")
        st.json(ids)

        st.write("✅ Résumé des données chargées :")
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("GEODIS lignes", len(df_geodis))
            st.metric("GEODIS départements", df_geodis["departement"].nunique())
            st.write(df_geodis["departement"].astype(str).unique()[:20])

        with col2:
            st.metric("DACHSER lignes", len(df_dachser))
            st.metric("DACHSER départements", df_dachser["departement"].nunique())
            st.write(df_dachser["departement"].astype(str).unique()[:20])

        with col3:
            st.metric("KUEHNE lignes", len(df_kuehne))
            st.metric("KUEHNE départements", df_kuehne["departement"].nunique())
            st.write(df_kuehne["departement"].astype(str).unique()[:20])

        with col4:
            st.metric("XPO lignes", len(df_xpo))
            st.metric("XPO départements", df_xpo["departement"].nunique())
            st.write(df_xpo["departement"].astype(str).unique()[:20])

        st.write("✅ Taxes :")
        st.json(taxes)

    except Exception as e:
        st.error(str(e))
        st.stop()


# -----------------------------------------------------------------------------
# FORM INPUTS
# -----------------------------------------------------------------------------
st.subheader("📍 Paramètres expédition")

departement = st.text_input("Département (ex : 35)", value="35").strip()

palette_parfaite = st.checkbox(
    "Palette parfaite (marchandise ne dépasse pas) — requis pour XPO",
    value=True
)

st.write("### Palettes")

# affichage palettes dynamiques
for i, p in enumerate(st.session_state.palettes):
    st.markdown(f"#### Palette {i+1}")
    c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 0.8])

    with c1:
        p["poids"] = st.number_input(f"Poids (kg) {i+1}", min_value=0.0, value=float(p["poids"]), step=1.0, key=f"poids_{i}")
    with c2:
        p["L"] = st.number_input(f"Longueur (cm) {i+1}", min_value=0.0, value=float(p["L"]), step=1.0, key=f"L_{i}")
    with c3:
        p["l"] = st.number_input(f"Largeur (cm) {i+1}", min_value=0.0, value=float(p["l"]), step=1.0, key=f"l_{i}")
    with c4:
        p["H"] = st.number_input(f"Hauteur (cm) {i+1}", min_value=0.0, value=float(p["H"]), step=1.0, key=f"H_{i}")

    with c5:
        if len(st.session_state.palettes) > 1:
            if st.button("🗑️ Supprimer", key=f"del_{i}"):
                st.session_state.palettes.pop(i)
                st.rerun()

# bouton ajouter palette
if st.button("➕ Ajouter une palette"):
    st.session_state.palettes.append({"poids": 50.0, "L": 80.0, "l": 120.0, "H": 100.0})
    st.rerun()


# -----------------------------------------------------------------------------
# COMPUTE
# -----------------------------------------------------------------------------
st.divider()
if st.button("✅ Calculer"):
    try:
        # reload data
        df_geodis, df_dachser, df_kuehne, df_xpo, taxes, ids = load_all_data(version="v7")

        results = compute_prices(
            departement=departement,
            palettes=st.session_state.palettes,
            palette_parfaite=palette_parfaite,
            df_geodis=df_geodis,
            df_dachser=df_dachser,
            df_kuehne=df_kuehne,
            df_xpo=df_xpo,
            taxes=taxes
        )

        df_res = pd.DataFrame(results)

        # Tri par prix avec taxe
        df_res["Prix_taxe_sort"] = pd.to_numeric(df_res["Prix_taxe"], errors="coerce")
        df_res = df_res.sort_values("Prix_taxe_sort", na_position="last").drop(columns=["Prix_taxe_sort"])

        st.subheader("📊 Résultats")
        st.dataframe(df_res, use_container_width=True)

        # meilleur transporteur
        valid = df_res.dropna(subset=["Prix_taxe"])
        if len(valid) > 0:
            best = valid.iloc[0]
            st.success(f"✅ Transporteur le moins cher : **{best['Transporteur']}** → **{best['Prix_taxe']} €**")
        else:
            st.warning("⚠️ Aucun transporteur n’a trouvé de tarif avec ces paramètres.")

    except Exception as e:
        # affichage en clair (pas redacted)
        st.error("Erreur pendant le calcul :")
        st.code(str(e))

st.write(st.secrets)

