import streamlit as st
import pandas as pd
import re

from gsheets_loader import load_sheet
from config_loader import load_constraints

from pricing_engine import (
    load_geodis_from_sheet,
    load_dachser_from_sheet,
    load_kuehne_from_sheet,
    load_xpo_from_sheet,
    load_taxes_from_sheet,
    load_zone_set_from_sheet,
    load_geodis_zone_urbaine_from_sheet,
    load_kuehne_zone_urbaine_from_sheet,
    kuehne_get_type,
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
    "GEODIS_ID", "GEODIS_TAB", "GEODIS_ZONE_TAB", "GEODIS_URBAINE_TAB",
    "DACHSER_ID", "DACHSER_TAB", "DACHSER_ZONE_TAB",
    "KUEHNE_ID", "KUEHNE_TAB", "KUEHNE_ZONE_TAB","KUEHNE_URBAINE_TAB",
    "XPO_ID", "XPO_TAB", "XPO_ZONE_TAB", "XPO_GV_TAB",
    "TAXE_GO_ID", "TAXE_GO_TAB",
    "RFA_TAB",
]

    missing = [k for k in keys if k not in s]
    if missing:
        raise ValueError(f"Secrets manquants dans [gsheets] : {missing}")

    return {
        "GEODIS_ID": s["GEODIS_ID"],
        "GEODIS_TAB": s["GEODIS_TAB"],
        "GEODIS_ZONE_TAB": s["GEODIS_ZONE_TAB"],
        "GEODIS_URBAINE_TAB": s["GEODIS_URBAINE_TAB"],

        "DACHSER_ID": s["DACHSER_ID"],
        "DACHSER_TAB": s["DACHSER_TAB"],
        "DACHSER_ZONE_TAB": s["DACHSER_ZONE_TAB"],

        "KUEHNE_ID": s["KUEHNE_ID"],
        "KUEHNE_TAB": s["KUEHNE_TAB"],
        "KUEHNE_ZONE_TAB": s["KUEHNE_ZONE_TAB"],
        "KUEHNE_URBAINE_TAB": s["KUEHNE_URBAINE_TAB"],

        "XPO_ID": s["XPO_ID"],
        "XPO_TAB": s["XPO_TAB"],
        "XPO_ZONE_TAB": s["XPO_ZONE_TAB"],
        "XPO_GV_TAB": s["XPO_GV_TAB"],

        "TAXE_ID": s["TAXE_GO_ID"],
        "TAXE_TAB": s["TAXE_GO_TAB"],
        "RFA_TAB": s["RFA_TAB"],
    }

def scroll_to_results():
    st.markdown('<div id="results"></div>', unsafe_allow_html=True)
    st.markdown('<script>document.getElementById("results").scrollIntoView({behavior: "smooth"});</script>', unsafe_allow_html=True)

# ---------------------------------------------------------------------
# Charger toutes les données Google Sheets (cache)
# ---------------------------------------------------------------------
@st.cache_data(show_spinner=True)
def load_all_data(version="v1"):
    ids = get_ids_from_secrets()

    # RAW
    df_geodis_raw  = load_sheet(ids["GEODIS_ID"],  ids["GEODIS_TAB"])
    df_geodis_zone_raw = load_sheet(ids["GEODIS_ID"], ids["GEODIS_ZONE_TAB"])
    df_geodis_urbaine_raw = load_sheet(ids["GEODIS_ID"], ids["GEODIS_URBAINE_TAB"])

    df_dachser_raw = load_sheet(ids["DACHSER_ID"], ids["DACHSER_TAB"])
    df_dachser_zone_raw = load_sheet(ids["DACHSER_ID"], ids["DACHSER_ZONE_TAB"])

    df_kuehne_raw  = load_sheet(ids["KUEHNE_ID"], ids["KUEHNE_TAB"])
    df_kuehne_zone_raw = load_sheet(ids["KUEHNE_ID"], ids["KUEHNE_ZONE_TAB"])
    df_kuehne_urbaine_raw = load_sheet(ids["KUEHNE_ID"], ids["KUEHNE_URBAINE_TAB"])
    kuehne_cp_to_type, kuehne_ranges, kuehne_dept_prefix_type = load_kuehne_zone_urbaine_from_sheet(df_kuehne_urbaine_raw)


    df_xpo_raw       = load_sheet(ids["XPO_ID"], ids["XPO_TAB"])
    df_xpo_zone_raw  = load_sheet(ids["XPO_ID"], ids["XPO_ZONE_TAB"])
    df_xpo_gv_raw    = load_sheet(ids["XPO_ID"], ids["XPO_GV_TAB"])

    # Taxes et RFA viennent du même fichier mais onglets différents
    df_taxe_raw = load_sheet(ids["TAXE_ID"], ids["TAXE_TAB"])
    df_rfa_raw  = load_sheet(ids["TAXE_ID"], ids["RFA_TAB"])

    # PARSE tarifs
    df_geodis  = load_geodis_from_sheet(df_geodis_raw)
    df_dachser = load_dachser_from_sheet(df_dachser_raw)
    df_kuehne  = load_kuehne_from_sheet(df_kuehne_raw)
    df_xpo     = load_xpo_from_sheet(df_xpo_raw)

    # PARSE taxes/rfa
    taxes = load_taxes_from_sheet(df_taxe_raw)
    rfa   = load_taxes_from_sheet(df_rfa_raw)

    # PARSE zones (sets de CP)
    geodis_zone_difficile = load_zone_set_from_sheet(df_geodis_zone_raw)
    geodis_cp_to_zone, geodis_ranges, geodis_dept_prefix_zone = load_geodis_zone_urbaine_from_sheet(df_geodis_urbaine_raw)

    kuehne_zone = load_zone_set_from_sheet(df_kuehne_zone_raw)
    kuehne_cp_to_type, kuehne_ranges, kuehne_dept_prefix_type = load_kuehne_zone_urbaine_from_sheet(df_kuehne_urbaine_raw)  # ✅ OK

    dachser_zone = load_zone_set_from_sheet(df_dachser_zone_raw)
    xpo_acces_difficile = load_zone_set_from_sheet(df_xpo_zone_raw)
    xpo_grande_ville = load_zone_set_from_sheet(df_xpo_gv_raw)

    return (
    df_geodis, df_dachser, df_kuehne, df_xpo,
    taxes, rfa,
    geodis_zone_difficile, geodis_cp_to_zone, geodis_ranges, geodis_dept_prefix_zone,
    kuehne_zone, kuehne_cp_to_type, kuehne_ranges, kuehne_dept_prefix_type,  # ✅ ici
    dachser_zone,
    xpo_acces_difficile, xpo_grande_ville,
    ids
)

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
    st.session_state.palettes = [{"poids": 100.0, "L": 120.0, "l": 80.0, "H": 100.0, "is_europe": False}]

# ---------------------------------------------------------------------
# Debug caché UI (uniquement en debug)
# ---------------------------------------------------------------------
if DEBUG:
    with st.expander("🛠️ Debug / Données chargées", expanded=False):
        try:
            (df_geodis, df_dachser, df_kuehne, df_xpo,taxes, rfa, geodis_zone_difficile, geodis_cp_to_zone, geodis_ranges, geodis_dept_prefix_zone, kuehne_zone, kuehne_cp_to_type, kuehne_ranges, kuehne_dept_prefix_type, dachser_zone, xpo_acces_difficile, xpo_grande_ville, ids) = load_all_data(version="v9")

            constraints = get_constraints(version="v1")

            st.write("DEBUG constraints KUEHNE:", constraints.get("KUEHNE"))
            st.write("DEBUG keys:", list(constraints.keys()))


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

code_postal = st.text_input("Code postal (ex : 35000)", value="35000").strip()

if not re.fullmatch(r"\d{5}", code_postal):
    st.error("Code postal invalide : 5 chiffres (ex: 35000).")
    st.stop()

departement = code_postal[:2]

constraints_ui = get_constraints(version="v1")
cfg_xpo_ui = constraints_ui.get("XPO", {})
xpo_enabled_ui = cfg_xpo_ui.get("enabled", True)


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
    st.session_state["palette_parfaite"] = False

# --- Toggle (UN SEUL, state géré par Streamlit) ---
st.toggle(
    "Palette parfaite (requis XPO)",
    key="palette_parfaite"
)

palette_parfaite = st.session_state["palette_parfaite"]

# --- Carte dynamique (APRÈS le toggle) ---
if palette_parfaite:
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

st.write("### Palettes")

# ---------------------------------------------------------------------
# Boucle d'affichage des palettes existantes
# ---------------------------------------------------------------------
for i, p in enumerate(st.session_state.palettes):
    st.markdown(f"#### Palette {i+1}")

    # Initialisation / Defaults
    p.setdefault("is_europe", False)
    p.setdefault("L", 120.0)
    p.setdefault("l", 80.0)
    p.setdefault("H", 100.0)
    p.setdefault("poids", 50.0)

    c0, c1, c2, c3, c4, c5 = st.columns([1.2, 1, 1, 1, 1, 0.8])

    with c0:
        p["is_europe"] = st.toggle(f"Palette Europe", value=p["is_europe"], key=f"is_europe_{i}")

    with c1:
        p["poids"] = st.number_input(f"Poids (kg) {i+1}", min_value=0.0, value=float(p["poids"]), key=f"poids_{i}")

    # --- LOGIQUE DE FORMAT ---
    allowed_formats = [
        {"label": "120 x 80", "dims": [120.0, 80.0]},
        {"label": "60 x 80",  "dims": [60.0, 80.0]},
        {"label": "120 x 100", "dims": [120.0, 100.0]}
    ]

    if palette_parfaite:
        # MODE PARFAIT : On force le choix dans la liste
        with c2:
            current_dims = [p["L"], p["l"]]
            idx_default = 0
            for idx, fmt in enumerate(allowed_formats):
                if fmt["dims"] == current_dims:
                    idx_default = idx
                    break
            
            # Ici, on ne bloque (disabled) QUE si c'est Europe ET Parfaite
            lock_select = p["is_europe"]
            
            selected_fmt = st.selectbox(
                f"Format {i+1}",
                options=allowed_formats,
                format_func=lambda x: x["label"],
                index=0 if lock_select else idx_default,
                key=f"select_format_{i}",
                disabled=lock_select
            )
            p["L"], p["l"] = selected_fmt["dims"]
        
        with c3:
            st.text_input("Largeur", value=f"{p['l']} cm", key=f"l_view_{i}", disabled=True)
    
    else:
        # MODE LIBRE : L'utilisateur fait ce qu'il veut
        # Si on vient de cocher Europe, on suggère 120x80 mais on ne BLOQUE PAS
        with c2:
            p["L"] = st.number_input(
                f"Longueur (cm)", 
                min_value=0.0, 
                value=float(p["L"]), 
                key=f"L_{i}", 
                disabled=False  # <--- CHANGEMENT ICI : Jamais bloqué en mode libre
            )
        with c3:
            p["l"] = st.number_input(
                f"largeur (cm)", 
                min_value=0.0, 
                value=float(p["l"]), 
                key=f"l_{i}", 
                disabled=False  # <--- CHANGEMENT ICI : Jamais bloqué en mode libre
            )

    with c4:
        p["H"] = st.number_input(f"Hauteur (cm)", min_value=0.0, value=float(p["H"]), key=f"H_{i}")

    with c5:
        if len(st.session_state.palettes) > 1:
            if st.button("🗑️", key=f"del_{i}"):
                st.session_state.palettes.pop(i)
                st.rerun()

# ---------------------------------------------------------------------
# BOUTON AJOUTER (Bien en dehors de la boucle)
# ---------------------------------------------------------------------
st.write("") # Petit espacement
if st.button("➕ Ajouter une palette", use_container_width=False):
    st.session_state.palettes.append({"poids": 50.0, "L": 120.0, "l": 80.0, "H": 100.0, "is_europe": False})
    st.rerun()

# ---------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------
st.divider()

if st.button("✅ Calculer", use_container_width=True):
    # On place une ancre invisible au point où on veut que la page s'arrête
    st.markdown('<div id="result_section"></div>', unsafe_allow_html=True)
    
    try:
        df_geodis, df_dachser, df_kuehne, df_xpo, taxes, rfa, geodis_zone_difficile, geodis_cp_to_zone, geodis_ranges, geodis_dept_prefix_zone, kuehne_zone, kuehne_cp_to_type, kuehne_ranges, kuehne_dept_prefix_type, dachser_zone, xpo_acces_difficile, xpo_grande_ville, ids = load_all_data(version="v9")
        constraints = get_constraints(version="v1")

        results = compute_prices(
            departement=departement,
            code_postal=code_postal,
            geodis_zone_difficile=geodis_zone_difficile,
            geodis_cp_to_zone=geodis_cp_to_zone,
            geodis_ranges=geodis_ranges,
            geodis_dept_prefix_zone=geodis_dept_prefix_zone,
            kuehne_zone=kuehne_zone,
            kuehne_cp_to_type=kuehne_cp_to_type,
            kuehne_ranges=kuehne_ranges,
            kuehne_dept_prefix_type=kuehne_dept_prefix_type,
            dachser_zone=dachser_zone,
            xpo_acces_difficile=xpo_acces_difficile,
            xpo_grande_ville=xpo_grande_ville,
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

        # --- Affichage en colonnes ---
        h_col1, h_col2, h_col3, h_col4 = st.columns([1.5, 1, 1, 4.5])
        with h_col1: st.markdown("**Transporteur**")
        with h_col2: st.markdown("**Base €**")
        with h_col3: st.markdown("**Total €**")
        with h_col4: st.markdown("**Informations détaillées**")
        st.divider()

        for _, row in df_res.iterrows():
            is_best = (row["Prix_taxe"] == df_res["Prix_taxe"].min()) and pd.notnull(row["Prix_taxe"])
            r_col1, r_col2, r_col3, r_col4 = st.columns([1.5, 1, 1, 4.5])
            
            with r_col1:
                st.write(f"**{row['Transporteur']}**" if is_best else row['Transporteur'])
            with r_col2:
                st.write(f"{row['Prix_base']:.2f} €" if pd.notnull(row['Prix_base']) else "-")
            with r_col3:
                if is_best:
                    st.success(f"{row['Prix_taxe']:.2f} €")
                else:
                    st.write(f"{row['Prix_taxe']:.2f} €" if pd.notnull(row['Prix_taxe']) else "-")
            with r_col4:
                st.caption(row['Info'])
            
            st.markdown('<hr style="margin:0; padding:0; border-top:1px solid #eee;">', unsafe_allow_html=True)

        valid = df_res.dropna(subset=["Prix_taxe"])
        if len(valid) > 0:
            best = valid.iloc[0]
            st.success(f"✅ Transporteur le moins cher : **{best['Transporteur']}** → **{best['Prix_taxe']} €**")
        else:
            st.warning("⚠️ Merci de faire une demande d'affretement.")

        # --- LE SCRIPT DE SCROLL AUTOMATIQUE ---
        # On force le scroll vers l'ancre créée au début du bloc
        st.components.v1.html(
            """
            <script>
                var v = window.parent.document.getElementById("result_section");
                if (v) { v.scrollIntoView({behavior: "smooth"}); }
            </script>
            """,
            height=0,
        )

    except Exception as e:
        st.error("Erreur pendant le calcul :")
        st.code(str(e))


