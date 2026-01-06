import pandas as pd
import numpy as np
import math
import re

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
    m = re.search(r"(\d{2})", str(x))
    return m.group(1) if m else None

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
    Sheet format:
    Transporteurs | Taux taxe gasoil
    """
    df = df_raw.copy()
    df.columns = df.iloc[0]
    df = df.iloc[1:].copy()

    df.columns = [str(c).strip() for c in df.columns]
    df["Transporteurs"] = df["Transporteurs"].astype(str).str.strip().str.upper()
    df["Taux taxe gasoil"] = df["Taux taxe gasoil"].apply(to_float)

    return dict(zip(df["Transporteurs"], df["Taux taxe gasoil"]))

def appliquer_taxe(prix_base, transporteur, taxes):
    if pd.isna(prix_base):
        return np.nan
    taux = taxes.get(transporteur.upper(), 0)
    return prix_base * (1 + (taux / 100))

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

    header_row = _detect_header_row(df, keywords=("kg", "à"), min_matches=5)
    if header_row is None:
        raise ValueError("GEODIS: impossible de détecter la ligne des tranches.")

    headers = df.iloc[header_row].tolist()
    data_start = _detect_first_data_row(df, header_row + 1, col=0)
    if data_start is None:
        data_start = header_row + 1

    data = df.iloc[data_start:].copy()
    data = data.dropna(how="all")

    # Ajuster taille des headers
    headers = headers[:data.shape[1]]
    data.columns = headers

    # ✅ FIX : supprimer colonnes dupliquées
    data = data.loc[:, ~pd.Index(data.columns).duplicated()].copy()

    # Trouver colonne département
    dept_candidates = [
        c for c in data.columns
        if isinstance(c, str) and ("depart" in c.lower() or "dpt" in c.lower())
    ]
    if dept_candidates:
        dept_col = dept_candidates[0]
    else:
        dept_col = data.columns[0]

    data = data.rename(columns={dept_col: "departement"})
    data["departement"] = data["departement"].apply(extract_dept)

    # supprimer lignes qui n’ont pas de département
    data = data[data["departement"].notna()].copy()

    for col in data.columns:
        if col != "departement":
            data[col] = data[col].apply(to_float)

    return data

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
    XPO: colonnes du type:
    '.01 pal pal-.50 pal pal'
    '.51 pal pal-1.00 pal pal'
    '2.01 pal pal-3.00 pal pal'
    etc.
    """
    df = df_raw.copy()

    # Détecter header row (celle contenant 'pal')
    header_row = None
    for i in range(min(len(df), 80)):
        row = df.iloc[i].astype(str).str.lower()
        if row.str.contains("pal").sum() >= 5:
            header_row = i
            break

    if header_row is None:
        raise ValueError("XPO: ligne entête introuvable.")

    headers = df.iloc[header_row].tolist()
    data_start = _detect_first_data_row(df, header_row + 1, col=0)
    if data_start is None:
        data_start = header_row + 1

    data = df.iloc[data_start:].copy()
    data = data.dropna(how="all")

    headers = headers[:data.shape[1]]
    data.columns = headers

    data = data.rename(columns={data.columns[0]: "departement"})
    data["departement"] = data["departement"].apply(extract_dept)

    for col in data.columns:
        if col != "departement":
            data[col] = data[col].apply(to_float)

    data = data[data["departement"].notna()]
    return data

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
    r = df[df["departement"] == dep]
    if r.empty:
        return np.nan
    row = r.iloc[0]
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

    if poids_total <= 100:
        seuil = next((s for s in seuils if poids_total <= s), None)
        if seuil is None:
            return np.nan
        return row[str(seuil)]

    poids_arr = arrondi_10kg(poids_total)

    # on prend la dernière colonne <= poids_total
    seuil = max([s for s in seuils if s <= poids_total], default=None)
    if seuil is None:
        return np.nan

    prix_100 = row[str(seuil)]
    return prix_100 * (poids_arr / 100)

# ============================================================
# XPO
# ============================================================

def calcul_palettes_facturees_xpo(poids_palettes):
    """
    Règle:
    - si plus de 1 palette : on facture au nb entier de palettes (pas de demi)
    - si 1 palette : <200kg => 0.5 ; sinon 1
    """
    if len(poids_palettes) > 1:
        return float(len(poids_palettes))
    return 0.5 if poids_palettes[0] < 200 else 1.0

def trouver_colonne_xpo(row, total_palettes):
    """
    Trouve la bonne colonne XPO en fonction du nb palettes facturé.
    Colonne typique: '.51 pal pal-1.00 pal pal'
    """
    for col in row.index:
        if not isinstance(col, str):
            continue
        if "pal" not in col.lower():
            continue

        nums = re.findall(r"[0-9.]+", col.replace(",", "."))
        if len(nums) >= 2:
            a = float(nums[0]); b = float(nums[1])

            # Important: si total_palettes = 2, on doit aller sur 2.01-3.00 pal
            if total_palettes > 1 and a < 1.01:
                continue

            if a <= total_palettes <= b:
                return col

    return None

def prix_xpo(df_xpo, departement, poids_palettes, hauteur_cm, palette_parfaite):
    dep = str(departement).zfill(2)

    if not palette_parfaite:
        return np.nan, "XPO ignoré : palette parfaite obligatoire"
    if hauteur_cm > 220:
        return np.nan, "XPO ignoré : hauteur > 220 cm"

    total_pal = calcul_palettes_facturees_xpo(poids_palettes)

    r = df_xpo[df_xpo["departement"] == dep]
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
                   df_geodis, df_dachser, df_kuehne, df_xpo, taxes):

    poids_total = sum(p["poids"] for p in palettes)
    poids_palettes = [p["poids"] for p in palettes]
    hauteur_max = max(p["H"] for p in palettes)

    results = []

    # GEODIS
    base = prix_transporteurs_kg(df_geodis, departement, poids_total)
    results.append(("GEODIS", base, appliquer_taxe(base, "GEODIS", taxes), f"Poids total {poids_total} kg"))

    # DACHSER
    base = prix_transporteurs_kg(df_dachser, departement, poids_total)
    results.append(("DACHSER", base, appliquer_taxe(base, "DACHSER", taxes), f"Poids total {poids_total} kg"))

    # KUEHNE
    base = prix_kuehne(df_kuehne, departement, poids_total)
    results.append(("KUEHNE", base, appliquer_taxe(base, "KUEHNE", taxes), f"Poids total {poids_total} kg"))

    # XPO
    base, info = prix_xpo(df_xpo, departement, poids_palettes, hauteur_max, palette_parfaite)
    results.append(("XPO", base, appliquer_taxe(base, "XPO", taxes), info))

    out = []
    for t, base, total, info in results:
        out.append({
            "Transporteur": t,
            "Prix_base": None if pd.isna(base) else round(float(base), 2),
            "Prix_taxe": None if pd.isna(total) else round(float(total), 2),
            "Info": info
        })

    return out
