import pandas as pd
import numpy as np
import math
import re
from config_loader import load_constraints

# ============================================================
# UTILS
# ============================================================

def to_float(x):
    if x is None or str(x).strip() == "":
        return np.nan
    x = str(x).replace("€", "").replace(" ", "").replace(",", ".")
    try:
        return float(x)
    except:
        return np.nan

def arrondi_10kg(poids):
    return math.ceil(poids / 10) * 10

def extract_dept(x):
    if x is None:
        return None

    # normalisation
    s = str(x).strip()

    # cas "1.0" ou "35.0"
    if re.fullmatch(r"\d+\.0", s):
        s = s.replace(".0", "")

    # cas "1" ou "35"
    if re.fullmatch(r"\d{1,2}", s):
        return s.zfill(2)

    # cas "Dpt 35", "35 - truc", "(35)"
    m = re.search(r"(\d{1,2})", s)
    if m:
        return m.group(1).zfill(2)

    return None


def parse_range(colname):
    """
    Parse des colonnes du type '0 à 4 kg', '100.1-150.0 kg', etc.
    Renvoie (min,max) ou None
    """
    if not isinstance(colname, str):
        return None
    col = colname.lower().replace("kg", "").strip().replace(",", ".")

    # formats "0 à 4"
    m = re.search(r"([0-9.]+)\s*à\s*([0-9.]+)", col)
    if m:
        return float(m.group(1)), float(m.group(2))

    # formats "0.1-29.0"
    m = re.search(r"([0-9.]+)\s*-\s*([0-9.]+)", col)
    if m:
        return float(m.group(1)), float(m.group(2))

    return None

# ============================================================
# TAXES
# ============================================================

def load_taxes_from_sheet(df_raw):
    """
    Le sheet taxe_go contient :
      - Onglet taxe_go : Transporteurs | Taux taxe gasoil
      - Onglet rfa     : Transporteurs | Taux RFA
    Mais ici df_raw est déjà un DataFrame de l'onglet chargé.
    Donc on garde le parsing générique :
    """
    df = df_raw.copy()
    df.columns = df.iloc[0]
    df = df.iloc[1:].copy()

    df.columns = [str(c).strip() for c in df.columns]
    df["Transporteurs"] = df["Transporteurs"].astype(str).str.strip().str.upper()

    # colonne possible : "Taux taxe gasoil" ou "Taux RFA"
    value_col = [c for c in df.columns if "taux" in c.lower()][0]
    df[value_col] = df[value_col].apply(to_float)

    return dict(zip(df["Transporteurs"], df[value_col]))

def appliquer_taxe(prix_base, transporteur, taxes):
    if pd.isna(prix_base):
        return np.nan
    taux = taxes.get(transporteur.upper(), 0)
    return prix_base * (1 + (taux / 100))

def appliquer_taxe_et_rfa(prix_base, transporteur, taxes, rfa):
    if pd.isna(prix_base):
        return np.nan
    t = taxes.get(transporteur.upper(), 0) or 0
    r = rfa.get(transporteur.upper(), 0) or 0
    return prix_base * (1 + (t / 100)) * (1 - (r / 100))

# ============================================================
# PARSERS GOOGLE SHEETS
# ============================================================

def _detect_header_row(df, keywords=("kg",), min_matches=5, max_scan=80):
    for i in range(min(len(df), max_scan)):
        row = df.iloc[i].astype(str).str.lower()
        if sum(row.str.contains(k).sum() for k in keywords) >= min_matches:
            return i
    return None

def _detect_first_data_row(df, start, col=0, max_scan=60):
    """
    Détecte la première ligne contenant un département (01, 02, ..., 95)
    """
    for i in range(start, min(len(df), start + max_scan)):
        v = str(df.iloc[i, col]).strip()
        if re.match(r"^\d{1,2}$", v):
            return i
        if re.match(r"^\d{2}\s", v):  # ex: '01 AIN'
            return i
    return None

def load_geodis_from_sheet(df_raw):
    df = df_raw.copy()
    df.columns = df.iloc[0]
    df = df.iloc[1:].copy()

    df = df.loc[:, ~pd.Index(df.columns).duplicated()].copy()
    df = df.dropna(how="all")

    df = df.rename(columns={df.columns[0]: "departement"})
    df["departement"] = df["departement"].apply(extract_dept)
    df = df[df["departement"].notna()].copy()
    df["departement"] = df["departement"].astype(str).str.zfill(2)

    for col in df.columns:
        if col != "departement":
            df[col] = df[col].apply(to_float)

    return df


def load_dachser_from_sheet(df_raw):
    df = df_raw.copy()

    # 1) détecter la première ligne contenant un département dans la 1ère colonne
    data_start = None
    for i in range(min(len(df), 120)):
        v = str(df.iloc[i, 0]).strip()
        if re.match(r"^\d{1,2}$", v):  # ex: 06
            data_start = i
            break

    if data_start is None:
        raise ValueError("DACHSER: impossible de trouver les lignes départements (06,07,etc).")

    # 2) Les headers sont en général la ligne juste au-dessus
    header_row = data_start - 1
    if header_row < 0:
        raise ValueError("DACHSER: impossible de déterminer la ligne d'entête.")

    headers = df.iloc[header_row].tolist()
    data = df.iloc[data_start:].copy()
    data = data.dropna(how="all")

    # Ajuster la taille des colonnes
    headers = headers[:data.shape[1]]
    data.columns = headers

    # Supprimer colonnes dupliquées
    data = data.loc[:, ~pd.Index(data.columns).duplicated()].copy()

    # Renommer première colonne en departement
    data = data.rename(columns={data.columns[0]: "departement"})
    data["departement"] = data["departement"].astype(str).str.strip().str.zfill(2)

    # Convertir prix
    for col in data.columns:
        if col != "departement":
            data[col] = data[col].apply(to_float)

    # Nettoyage
    data = data[data["departement"].str.match(r"^\d{2}$", na=False)]

    return data

def load_kuehne_from_sheet(df_raw):
    """
    KUEHNE: la 1ère ligne contient des seuils (1,30,40,...) etc.
    """
    df = df_raw.copy()

    header1 = df.iloc[0].tolist()
    cols = ["Pays", "departement", "Destination", "Difficulte", "Poids_reel"] + header1[5:]

    data = df.iloc[2:].copy()
    data.columns = cols
    data = data.dropna(how="all")

    data["departement"] = data["departement"].astype(str).str.strip()
    data = data[data["departement"].str.match(r"^\d{1,2}$", na=False)]
    data["departement"] = data["departement"].str.zfill(2)

    for col in data.columns:
        if col not in ["Pays", "departement", "Destination", "Difficulte", "Poids_reel"]:
            data[col] = data[col].apply(to_float)

    return data

def load_xpo_from_sheet(df_raw):
    """
    Lecture XPO depuis Google Sheets quand la feuille est déjà propre :
    - 1ère ligne = headers
    - colonne 0 = departement
    - colonnes suivantes = tranches palettes (0.01 pal-0.50 pal, etc.)
    OU colonnes simplifiées (1,2,3...) si tu as renommé en local
    """
    df = df_raw.copy()

    # Première ligne = header
    df.columns = df.iloc[0]
    df = df.iloc[1:].copy()

    # Nettoyage colonnes
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~pd.Index(df.columns).duplicated()].copy()

    # La première colonne doit être departement
    if df.columns[0].lower() != "departement":
        df = df.rename(columns={df.columns[0]: "departement"})

    df["departement"] = df["departement"].apply(extract_dept)
    df = df[df["departement"].notna()]
    df["departement"] = df["departement"].astype(str).str.zfill(2)

    # Conversion float
    for col in df.columns:
        if col != "departement":
            df[col] = df[col].apply(to_float)

    return df



# ============================================================
# CALCUL PRIX PAR TRANCHES (GEODIS / DACHSER)
# ============================================================

def trouver_prix_forfait(row, poids):
    for col in row.index:
        r = parse_range(col)
        if r:
            a, b = r
            if a <= poids <= b and poids <= 100:
                return row[col]
    return np.nan

def trouver_prix_100kg(row, poids):
    poids_arr = arrondi_10kg(poids)
    for col in row.index:
        r = parse_range(col)
        if r:
            a, b = r
            if a <= poids <= b and poids > 100:
                prix_100 = row[col]
                return prix_100 * (poids_arr / 100)
    return np.nan

def prix_transporteurs_kg(df, departement, poids_total):
    dep = str(departement).zfill(2)

    if "departement" not in df.columns:
        raise ValueError(f"ERREUR: colonne 'departement' absente. Colonnes: {df.columns.tolist()}")

    # DEBUG : voir si dep existe
    if dep not in df["departement"].astype(str).unique():
        raise ValueError(
            f"ERREUR: département {dep} introuvable dans la table.\n"
            f"Départements dispo (20): {df['departement'].astype(str).unique()[:20]}"
        )

    r = df[df["departement"].astype(str) == dep]
    if r.empty:
        raise ValueError(f"ERREUR: filtre département {dep} donne vide (incohérence).")

    row = r.iloc[0]

    # DEBUG : voir les colonnes tranches
    cols_ranges = [c for c in row.index if parse_range(c)]
    if not cols_ranges:
        raise ValueError(
            f"ERREUR: aucune colonne tranche reconnue par parse_range().\n"
            f"Colonnes: {list(row.index)[:30]}"
        )

    return trouver_prix_forfait(row, poids_total) if poids_total <= 100 else trouver_prix_100kg(row, poids_total)


# ============================================================
# KUEHNE
# ============================================================

def prix_kuehne(df, departement, poids_total):
    dep = str(departement).zfill(2)
    r = df[df["departement"] == dep]
    if r.empty:
        return np.nan

    row = r.iloc[0]
    seuils = sorted([int(c) for c in row.index if str(c).isdigit()])

    if not seuils:
        return np.nan

    seuil_max = max(seuils)

    # ✅ Si au-dessus du max, pas de tarif
    if poids_total > seuil_max:
        return np.nan

    # ✅ Forfait jusqu'à 100 kg
    if poids_total <= 100:
        seuil = next((s for s in seuils if poids_total <= s), None)
        if seuil is None:
            return np.nan
        return row[str(seuil)]

    # ✅ Au-delà de 100 : prix au 100kg arrondi à 10kg
    poids_arr = arrondi_10kg(poids_total)

    seuil = max([s for s in seuils if s <= poids_total], default=None)
    if seuil is None:
        return np.nan

    prix_100 = row[str(seuil)]
    return prix_100 * (poids_arr / 100)

    max_weight_cfg = constraints.get("KUEHNE", {}).get("max_weight_kg", None)
    if max_weight_cfg is not None and poids_total > max_weight_cfg:
        return np.nan


# ============================================================
# XPO
# ============================================================

def _format_ok(L, l, allowed_formats):
    dims = tuple(sorted([int(L), int(l)]))
    allowed = {tuple(sorted(x)) for x in allowed_formats}
    return dims in allowed

def _is_half_pallet(p, cfg_xpo):
    hp = cfg_xpo.get("half_pallet", {})
    if not hp.get("enabled", True):
        return False
    return p["poids"] <= hp.get("max_weight_kg", 200)

def _palettes_facturees(palettes, cfg_xpo):
    if len(palettes) > 1 and cfg_xpo.get("billing", {}).get("no_half_when_multiple", True):
        return float(len(palettes))

    # une seule palette
    p = palettes[0]
    if _is_half_pallet(p, cfg_xpo) and cfg_xpo.get("half_pallet", {}).get("only_if_single_palette", True):
        return 0.5
    return 1.0

def prix_xpo(df_xpo, departement, palettes, palette_parfaite, constraints):
    cfg_xpo = constraints.get("XPO", {})
    if not cfg_xpo.get("enabled", True):
        return np.nan, "XPO désactivé (config)"

    dep = str(departement).zfill(2)

    if cfg_xpo.get("palette_parfaite_required", False) and not palette_parfaite:
        return np.nan, "XPO ignoré : palette parfaite obligatoire"

    allowed_formats = cfg_xpo.get("allowed_formats_cm", [])
    max_h = cfg_xpo.get("max_height_cm", 220)
    max_w_full = cfg_xpo.get("max_weight_full_pallet_kg", 1000)

    # Vérifs palette par palette
    for i, p in enumerate(palettes):
        if p["H"] > max_h:
            return np.nan, f"XPO ignoré : palette {i+1} hauteur > {max_h} cm"
        if not _format_ok(p["L"], p["l"], allowed_formats):
            return np.nan, f"XPO ignoré : palette {i+1} format {p['L']}x{p['l']} non accepté"
        if p["poids"] > max_w_full:
            return np.nan, f"XPO ignoré : palette {i+1} > {max_w_full} kg"

    total_pal = _palettes_facturees(palettes, cfg_xpo)

    # département présent ?
    r = df_xpo[df_xpo["departement"].astype(str).str.zfill(2) == dep]
    if r.empty:
        return np.nan, "XPO ignoré : département absent"

    row = r.iloc[0]
    col = trouver_colonne_xpo(row, total_pal)
    if col is None:
        return np.nan, f"XPO ignoré : aucune tranche pour {total_pal} palettes"

    return row[col], f"XPO : {total_pal} palette(s), tranche {col}"


# ============================================================
# API PRINCIPALE
# ============================================================

def compute_prices(departement, palettes, palette_parfaite,
                   df_geodis, df_dachser, df_kuehne, df_xpo, taxes, rfa,
                   constraints=None):

    if constraints is None:
        constraints = load_constraints()

    poids_total = sum(p["poids"] for p in palettes)
    poids_palettes = [p["poids"] for p in palettes]
    hauteur_max = max(p["H"] for p in palettes)

    results = []

    # GEODIS
    base = prix_transporteurs_kg(df_geodis, departement, poids_total)
    results.append(("GEODIS", base, appliquer_taxe_et_rfa(base, "GEODIS", taxes, rfa), f"Poids total {poids_total} kg"))


    # DACHSER
    base = prix_transporteurs_kg(df_dachser, departement, poids_total)
    results.append(("DACHSER", base, appliquer_taxe_et_rfa(base, "DACHSER", taxes, rfa), f"Poids total {poids_total} kg"))

    # KUEHNE
    base = prix_kuehne(df_kuehne, departement, poids_total)
    results.append(("KUEHNE", base, appliquer_taxe_et_rfa(base, "KUEHNE", taxes, rfa), f"Poids total {poids_total} kg"))

    # XPO
    base, info = prix_xpo(df_xpo, departement, palettes, palette_parfaite, constraints)
    results.append(("XPO", base, appliquer_taxe_et_rfa(base, "XPO", taxes, rfa), info))


    out = []
    for t, base, total, info in results:
        out.append({
            "Transporteur": t,
            "Prix_base": None if pd.isna(base) else round(float(base), 2),
            "Prix_taxe": None if pd.isna(total) else round(float(total), 2),
            "Info": info
        })

    return out
