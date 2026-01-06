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

st.set_page_config(page_title="Transporteur - Calcul tarif", layout="wide")
st.title("🚚 Comparateur Transporteurs")

# ---------------- Init session palettes ----------------
if "palettes" not in st.session_state:
    st.session_state.palettes = [{"poids": 0.0, "L": 120.0, "l": 80.0, "H": 100.0}]

def add_palette():
    st.session_state.palettes.append({"poids": 0.0, "L": 120.0, "l": 80.0, "H": 100.0})

def remove_palette(i):
    st.session_state.palettes.pop(i)

# ---------------- Sidebar ----------------
st.sidebar.header("Paramètres")

departement = st.sidebar.text_input("Département (2 chiffres)", value="35")
palette_parfaite = st.sidebar.checkbox("Palette parfaite (XPO)", value=True)

reload_btn = st.sidebar.button("🔄 Recharger les tarifs")

# ---------------- Load all sheets ----------------
@st.cache_data(show_spinner=False)
def load_all_data():
    ids = st.secrets["gsheets"]

    df_taxe_raw = load_sheet(ids["TAXE_GO_ID"], ids["TAXE_GO_TAB"])
    df_kuehne_raw = load_sheet(ids["KUEHNE_ID"], ids["KUEHNE_TAB"])
    df_xpo_raw = load_sheet(ids["XPO_ID"], ids["XPO_TAB"])
    df_geodis_raw = load_sheet(ids["GEODIS_ID"], ids["GEODIS_TAB"])
    df_dachser_raw = load_sheet(ids["DACHSER_ID"], ids["DACHSER_TAB"])

    taxes = load_taxes_from_sheet(df_taxe_raw)

    df_geodis = load_geodis_from_sheet(df_geodis_raw)
    df_dachser = load_dachser_from_sheet(df_dachser_raw)
    df_kuehne = load_kuehne_from_sheet(df_kuehne_raw)
    df_xpo = load_xpo_from_sheet(df_xpo_raw)

    return df_geodis, df_dachser, df_kuehne, df_xpo, taxes

if reload_btn:
    load_all_data.clear()

with st.spinner("Chargement des tarifs..."):
    df_geodis, df_dachser, df_kuehne, df_xpo, taxes = load_all_data()

st.subheader("DEBUG SOURCES")

st.write("GEODIS_ID:", ids["GEODIS_ID"])
st.write("GEODIS_TAB:", ids["GEODIS_TAB"])
st.write("GEODIS nb lignes DF:", len(df_geodis))
st.write("GEODIS nb départements:", df_geodis["departement"].nunique())
st.write("GEODIS départements (20):", df_geodis["departement"].astype(str).unique()[:20])


DEBUG = True

if DEBUG:
    st.subheader("DEBUG - Données chargées")

    st.write("✅ GEODIS columns:", df_geodis.columns.tolist())
    st.write("✅ GEODIS départements:", sorted(df_geodis["departement"].dropna().unique())[:30])
    st.dataframe(df_geodis.head(5))

    st.write("✅ DACHSER columns:", df_dachser.columns.tolist())
    st.write("✅ DACHSER départements:", sorted(df_dachser["departement"].dropna().unique())[:30])
    st.dataframe(df_dachser.head(5))

    st.write("✅ XPO columns:", df_xpo.columns.tolist())
    st.write("✅ XPO départements:", sorted(df_xpo["departement"].dropna().unique())[:30])
    st.dataframe(df_xpo.head(5))

    st.write("✅ TAXES:", taxes)


# ---------------- UI palettes ----------------
st.subheader("📦 Palettes")

c_add, c_txt = st.columns([1, 4])
with c_add:
    st.button("➕ Ajouter une palette", on_click=add_palette)
with c_txt:
    st.caption("Renseigne Poids + Dimensions. Pour XPO : H max = 220 cm, palette parfaite obligatoire.")

for i, p in enumerate(st.session_state.palettes):
    st.markdown(f"### Palette {i+1}")
    c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 0.4])

    with c1:
        p["poids"] = st.number_input(f"Poids (kg)", min_value=0.0, step=1.0, value=float(p["poids"]), key=f"poids_{i}")
    with c2:
        p["L"] = st.number_input(f"Longueur (cm)", min_value=0.0, step=1.0, value=float(p["L"]), key=f"L_{i}")
    with c3:
        p["l"] = st.number_input(f"Largeur (cm)", min_value=0.0, step=1.0, value=float(p["l"]), key=f"l_{i}")
    with c4:
        p["H"] = st.number_input(f"Hauteur (cm)", min_value=0.0, step=1.0, value=float(p["H"]), key=f"H_{i}")

    with c5:
        if len(st.session_state.palettes) > 1:
            st.button("➖", key=f"remove_{i}", on_click=remove_palette, args=(i,))

st.divider()

# ---------------- Compute ----------------
if st.button("✅ Calculer"):
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

    df = pd.DataFrame(results)
    st.subheader("📊 Résultats (taxe incluse)")

    df_sort = df.copy()
    df_sort["prix"] = pd.to_numeric(df_sort["Prix_taxe"], errors="coerce")
    df_sort = df_sort.sort_values("prix", na_position="last").drop(columns=["prix"])

    st.dataframe(df_sort, use_container_width=True)

    df_valid = df_sort.dropna(subset=["Prix_taxe"])
    if not df_valid.empty:
        best = df_valid.iloc[0]
        st.success(f"✅ Meilleur transporteur : **{best['Transporteur']}** — **{best['Prix_taxe']} €**")
        st.info(best["Info"])
    else:
        st.error("❌ Aucun transporteur disponible avec ces paramètres.")
