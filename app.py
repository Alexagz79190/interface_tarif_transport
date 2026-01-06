import streamlit as st
import pandas as pd
from sharepoint_loader import get_tarif_files_from_sharepoint
from pricing_engine import compute_prices

st.set_page_config(page_title="Choix Transporteur", layout="wide")

st.title("🚚 Sélection du transporteur le moins cher")

# ---------------- Init session palettes ----------------
if "palettes" not in st.session_state:
    st.session_state.palettes = [
        {"poids": 180.0, "L": 120.0, "l": 80.0, "H": 100.0}
    ]

def add_palette():
    st.session_state.palettes.append({"poids": 0.0, "L": 120.0, "l": 80.0, "H": 100.0})

def remove_palette(i):
    st.session_state.palettes.pop(i)

# ---------------- Sidebar ----------------
st.sidebar.header("Paramètres")

departement = st.sidebar.text_input("Département (2 chiffres)", value="35")
palette_parfaite = st.sidebar.checkbox("Palette parfaite (obligatoire pour XPO)", value=True)

reload_tarifs = st.sidebar.button("🔄 Recharger tarifs SharePoint")

# ---------------- Download tarifs ----------------
@st.cache_data(show_spinner=False)
def load_tarifs_cached():
    return get_tarif_files_from_sharepoint(st.secrets)

if reload_tarifs:
    load_tarifs_cached.clear()

with st.spinner("Chargement des tarifs depuis SharePoint..."):
    paths = load_tarifs_cached()

# ---------------- UI palettes ----------------
st.subheader("📦 Palettes")

col_add, col_info = st.columns([1, 3])
with col_add:
    st.button("➕ Ajouter une palette", on_click=add_palette)
with col_info:
    st.caption("Renseigne poids et dimensions pour chaque palette. XPO utilise la hauteur max (H).")

for i, p in enumerate(st.session_state.palettes):
    st.markdown(f"### Palette {i+1}")
    c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 0.5])

    with c1:
        p["poids"] = st.number_input(f"Poids (kg) - P{i}", min_value=0.0, step=1.0, value=float(p["poids"]), key=f"poids_{i}")
    with c2:
        p["L"] = st.number_input(f"Longueur (cm) - P{i}", min_value=0.0, step=1.0, value=float(p["L"]), key=f"L_{i}")
    with c3:
        p["l"] = st.number_input(f"Largeur (cm) - P{i}", min_value=0.0, step=1.0, value=float(p["l"]), key=f"l_{i}")
    with c4:
        p["H"] = st.number_input(f"Hauteur (cm) - P{i}", min_value=0.0, step=1.0, value=float(p["H"]), key=f"H_{i}")

    with c5:
        if len(st.session_state.palettes) > 1:
            st.button("➖", key=f"remove_{i}", on_click=remove_palette, args=(i,))

st.divider()

# ---------------- Compute ----------------
if st.button("✅ Calculer"):
    with st.spinner("Calcul en cours..."):
        results = compute_prices(departement, st.session_state.palettes, palette_parfaite, paths)

    df = pd.DataFrame(results)

    st.subheader("📊 Comparatif des prix (taxe incluse)")
    df_sorted = df.copy()
    df_sorted["Prix_taxe_numeric"] = pd.to_numeric(df_sorted["Prix_taxe"], errors="coerce")
    df_sorted = df_sorted.sort_values("Prix_taxe_numeric", na_position="last").drop(columns=["Prix_taxe_numeric"])

    st.dataframe(df_sorted, use_container_width=True)

    # Best
    df_valid = df_sorted.dropna(subset=["Prix_taxe"])
    if not df_valid.empty:
        best = df_valid.iloc[0]
        st.success(f"✅ Meilleur transporteur : **{best['Transporteur']}** — **{best['Prix_taxe']} €**")
        st.info(f"Détail : {best['Info']}")
    else:
        st.error("❌ Aucun transporteur n'a pu être calculé avec ces paramètres.")
