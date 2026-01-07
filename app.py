import streamlit as st
import pandas as pd

from gsheets_loader import load_sheet
from config_loader import load_constraints

from pricing_engine import (
    load_geodis_from_sheet,
    load_dachser_from_sheet,
    load_kuehne_from_sheet,
    load_xpo_from_sheet,
    load_taxes_from_sheet,
    compute_prices
)

# ------------------------------
# CONFIG
# ------------------------------
st.set_page_config(page_title="Comparateur Transport", layout="wide")
st.title("📦 Comparateur Tarif Transport")
colA, colB = st.columns(2)

with colA:
    if st.button("🔄 Actualiser données (tarifs)"):
        st.cache_data.clear()
        st.rerun()

with colB:
    if st.button("🔄 Actualiser contraintes"):
        st.cache_data.clear()
        st.rerun()


# ------------------------------
# DEBUG caché via secrets
# Dans Streamlit secrets :
# [app]
# DEBUG = true
# ------------------------------
DEBUG = st.secrets.get("app", {}).get("DEBUG", False)

# ---------------------------------------------------------------------
# Lire les IDs depuis st.secrets["gsheets"]
# ---------------------------------------------------------------------
def get_ids_from_secrets():
    if "gsheets" not in st.secrets:
        raise ValueError("Secrets: section [gsheets] introuvable")

    s = st.secrets["gsheets"]

    keys = [
        "GEODIS_ID", "GEODIS_TAB",
        "DACHSER_ID", "DACHSER_TAB",
        "KUEHNE_ID", "KUEHNE_TAB",
        "XPO_ID", "XPO_TAB",
        "TAXE_GO_ID", "TAXE_GO_TAB",
        "RFA_TAB",
    ]
    missing = [k for k in keys if k not in s]
    if missing:
        raise ValueError(f"Secrets manquants dans [gsheets] : {missing}")

    return {
        "GEODIS_ID": s["GEODIS_ID"],
        "GEODIS_TAB": s["GEODIS_TAB"],

        "DACHSER_ID": s["DACHSER_ID"],
        "DACHSER_TAB": s["DACHSER_TAB"],

        "KUEHNE_ID": s["KUEHNE_ID"],
        "KUEHNE_TAB": s["KUEHNE_TAB"],

        "XPO_ID": s["XPO_ID"],
        "XPO_TAB": s["XPO_TAB"],

        "TAXE_ID": s["TAXE_GO_ID"],
        "TAXE_TAB": s["TAXE_GO_TAB"],
        "RFA_TAB": s["RFA_TAB"],
    }

# ---------------------------------------------------------------------
# Charger toutes les données Google Sheets (cache)
# ---------------------------------------------------------------------
@st.cache_data(show_spinner=True)
def load_all_data(version="v1"):
    ids = get_ids_from_secrets()

    # RAW
    df_geodis_raw  = load_sheet(ids["GEODIS_ID"],  ids["GEODIS_TAB"])
    df_dachser_raw = load_sheet(ids["DACHSER_ID"], ids["DACHSER_TAB"])
    df_kuehne_raw  = load_sheet(ids["KUEHNE_ID"],  ids["KUEHNE_TAB"])
    df_xpo_raw     = load_sheet(ids["XPO_ID"],     ids["XPO_TAB"])

    # Taxes et RFA viennent du même fichier mais onglets différents
    df_taxe_raw    = load_sheet(ids["TAXE_ID"], ids["TAXE_TAB"])
    df_rfa_raw     = load_sheet(ids["TAXE_ID"], ids["RFA_TAB"])

    # PARSE
    df_geodis  = load_geodis_from_sheet(df_geodis_raw)
    df_dachser = load_dachser_from_sheet(df_dachser_raw)
    df_kuehne  = load_kuehne_from_sheet(df_kuehne_raw)
    df_xpo     = load_xpo_from_sheet(df_xpo_raw)

    taxes = load_taxes_from_sheet(df_taxe_raw)  # {GEODIS: 15.19, ...}
    rfa   = load_taxes_from_sheet(df_rfa_raw)   # {GEODIS: 2.50, ...}

    return df_geodis, df_dachser, df_kuehne, df_xpo, taxes, rfa, ids

# ---------------------------------------------------------------------
# Charger les contraintes YAML (cache)
# ---------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def get_constraints(version="v1"):
    return load_constraints("constraints.yaml")

# ---------------------------------------------------------------------
# Boutons reload (uniquement en debug)
# ---------------------------------------------------------------------
if DEBUG:
    colA, colB = st.columns(2)
    with colA:
        if st.button("🔄 Forcer rechargement données"):
            st.cache_data.clear()
            st.rerun()
    with colB:
        if st.button("📄 Recharger constraints.yaml"):
            st.cache_data.clear()
            st.rerun()

# ---------------------------------------------------------------------
# Init session palettes
# ---------------------------------------------------------------------
if "palettes" not in st.session_state:
    st.session_state.palettes = [{"poids": 100.0, "L": 80.0, "l": 120.0, "H": 100.0}]

# ---------------------------------------------------------------------
# Debug caché UI (uniquement en debug)
# ---------------------------------------------------------------------
if DEBUG:
    with st.expander("🛠️ Debug / Données chargées", expanded=False):
        try:
            df_geodis, df_dachser, df_kuehne, df_xpo, taxes, rfa, ids = load_all_data(version="v9")
            constraints = get_constraints(version="v1")

            st.write("✅ IDs / Onglets utilisés :")
            st.json(ids)

            st.write("✅ Contraintes YAML :")
            st.json(constraints)

            st.write("✅ Résumé chargement :")
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

            st.write("✅ RFA :")
            st.json(rfa)

        except Exception as e:
            st.error(str(e))
            st.stop()

# ---------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------
st.subheader("📍 Paramètres expédition")

departement = st.text_input("Département (ex : 35)", value="35").strip()

# ✅ Remplace le checkbox ici par le bloc PRO
# --- CSS carte toggle ---
st.markdown("""
<style>
.big-card {
    padding: 18px 22px;
    border-radius: 14px;
    margin-bottom: 10px;
    font-size: 20px;
    font-weight: 700;
    display: flex;
    justify-content: space-between;
    align-items: center;
    box-shadow: 0px 3px 12px rgba(0,0,0,0.08);
}
.card-ok {
    background: rgba(0, 200, 0, 0.12);
    border: 2px solid rgba(0, 160, 0, 0.45);
}
.card-nok {
    background: rgba(255, 0, 0, 0.10);
    border: 2px solid rgba(200, 0, 0, 0.35);
}
/* agrandir le toggle */
div[data-baseweb="switch"] {
    transform: scale(1.35);
}
</style>
""", unsafe_allow_html=True)

# --- Etat en session ---
if "palette_parfaite" not in st.session_state:
    st.session_state.palette_parfaite = True

# --- Carte dynamique ---
if st.session_state.palette_parfaite:
    st.markdown(
        """
        <div class="big-card card-ok">
            ✅ Palette parfaite (requis XPO)
            <span style="font-size:16px; font-weight:600;">ACTIVÉ</span>
        </div>
        """,
        unsafe_allow_html=True
    )
else:
    st.markdown(
        """
        <div class="big-card card-nok">
            ❌ Palette parfaite (requis XPO)
            <span style="font-size:16px; font-weight:600;">DÉSACTIVÉ</span>
        </div>
        """,
        unsafe_allow_html=True
    )

# --- Toggle ---
st.session_state.palette_parfaite = st.toggle(
    " ",
    value=st.session_state.palette_parfaite,
    label_visibility="collapsed"
)

palette_parfaite = st.session_state.palette_parfaite


st.write("### Palettes")

for i, p in enumerate(st.session_state.palettes):
    st.markdown(f"#### Palette {i+1}")
    c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 0.8])

    with c1:
        p["poids"] = st.number_input(
            f"Poids (kg) {i+1}", min_value=0.0, value=float(p["poids"]),
            step=1.0, key=f"poids_{i}"
        )
    with c2:
        p["L"] = st.number_input(
            f"Longueur (cm) {i+1}", min_value=0.0, value=float(p["L"]),
            step=1.0, key=f"L_{i}"
        )
    with c3:
        p["l"] = st.number_input(
            f"Largeur (cm) {i+1}", min_value=0.0, value=float(p["l"]),
            step=1.0, key=f"l_{i}"
        )
    with c4:
        p["H"] = st.number_input(
            f"Hauteur (cm) {i+1}", min_value=0.0, value=float(p["H"]),
            step=1.0, key=f"H_{i}"
        )

    with c5:
        if len(st.session_state.palettes) > 1:
            if st.button("🗑️ Supprimer", key=f"del_{i}"):
                st.session_state.palettes.pop(i)
                st.rerun()

if st.button("➕ Ajouter une palette"):
    st.session_state.palettes.append({"poids": 50.0, "L": 80.0, "l": 120.0, "H": 100.0})
    st.rerun()

# ---------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------
st.divider()

if st.button("✅ Calculer"):
    try:
        df_geodis, df_dachser, df_kuehne, df_xpo, taxes, rfa, ids = load_all_data(version="v9")
        constraints = get_constraints(version="v1")  # ✅ NEW

        results = compute_prices(
            departement=departement,
            palettes=st.session_state.palettes,
            palette_parfaite=palette_parfaite,
            df_geodis=df_geodis,
            df_dachser=df_dachser,
            df_kuehne=df_kuehne,
            df_xpo=df_xpo,
            taxes=taxes,
            rfa=rfa,
            constraints=constraints
        )

        df_res = pd.DataFrame(results)
        df_res["Prix_taxe_sort"] = pd.to_numeric(df_res["Prix_taxe"], errors="coerce")
        df_res = df_res.sort_values("Prix_taxe_sort", na_position="last").drop(columns=["Prix_taxe_sort"])

        st.subheader("📊 Résultats")
        st.dataframe(df_res, use_container_width=True)

        valid = df_res.dropna(subset=["Prix_taxe"])
        if len(valid) > 0:
            best = valid.iloc[0]
            st.success(f"✅ Transporteur le moins cher : **{best['Transporteur']}** → **{best['Prix_taxe']} €**")
        else:
            st.warning("⚠️ Merci de faire une demande d'affretement.")

    except Exception as e:
        st.error("Erreur pendant le calcul :")
        st.code(str(e))


