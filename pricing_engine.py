import pandas as pd
import numpy as np
import math
import re

# ---------------- UTILS ----------------
def to_float(x):
    if x is None or x == "":
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
    if not isinstance(colname, str):
        return None
    col = colname.lower().replace("kg", "").strip()

    m = re.search(r"([0-9.]+)\s*à\s*([0-9.]+)", col)
    if m:
        return float(m.group(1)), float(m.group(2))

    m = re.search(r"([0-9.]+)\s*-\s*([0-9.]+)", col)
    if m:
        return float(m.group(1)), float(m.group(2))

    return None

# ---------------- TAXES ----------------
def load_taxes_from_sheet(df_raw):
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

# ---------------- PARSERS Google Sheets ----------------
def load_geodis_from_sheet(df_raw):
    df = df_raw.copy()

    headers = df.iloc[9].tolist()
    data = df.iloc[11:].copy()
    data.columns = headers
    data = data.loc[:, ~pd.Index(data.columns).duplicated()]

    dept_col = data.columns[1]
    data = data.rename(columns={dept_col: "departement"})
    data["departement"] = data["departement"].apply(extract_dept)

    for col in data.columns:
        if col != "departement":
            data[col] = data[col].apply(to_float)
    return data

def load_dachser_from_sheet(df_raw):
    df = df_raw.copy()
    debuts = df.iloc[3].tolist()
    fins = df.iloc[4].tolist()

    data = df.iloc[10:].copy()
    data = data.loc[:, ~pd.Index(data.columns).duplicated()]

    data = data.rename(columns={data.columns[0]: "departement"})
    data["departement"] = data["departement"].astype(str).str.zfill(2)

    cols = list(data.columns)
    col_map = {}
    for idx in range(1, len(cols)):
        d = debuts[idx] if idx < len(debuts) else None
        f = fins[idx] if idx < len(fins) else None
        if d not in [None, ""] and f not in [None, ""]:
            col_map[cols[idx]] = f"{d}-{f} kg"

    data = data.rename(columns=col_map)

    for col in data.columns:
        if col != "departement":
            data[col] = data[col].apply(to_float)

    return data

def load_kuehne_from_sheet(df_raw):
    df = df_raw.copy()
    header1 = df.iloc[0].tolist()
    cols = ["Pays","departement","Destination","Difficulte","Poids_reel"] + header1[5:]

    data = df.iloc[2:].copy()
    data.columns = cols

    data["departement"] = data["departement"].astype(str).str.strip()
    data = data[data["departement"].str.match(r"^\d{1,2}$", na=False)]
    data["departement"] = data["departement"].str.zfill(2)

    for col in data.columns:
        if col not in ["Pays","departement","Destination","Difficulte","Poids_reel"]:
            data[col] = data[col].apply(to_float)

    return data

def load_xpo_from_sheet(df_raw):
    df = df_raw.copy()
    deb = df.iloc[13].tolist()
    fin = df.iloc[14].tolist()

    data = df.iloc[18:].copy()
    data = data.loc[:, ~pd.Index(data.columns).duplicated()]
    data = data.rename(columns={data.columns[0]: "departement"})
    data["departement"] = data["departement"].apply(extract_dept)

    cols = list(data.columns)
    col_map = {}
    for idx in range(1, min(12, len(cols))):
        d = deb[idx] if idx < len(deb) else None
        f = fin[idx] if idx < len(fin) else None
        if d not in [None, ""] and f not in [None, ""]:
            col_map[cols[idx]] = f"{d} pal-{f} pal"

    data = data.rename(columns=col_map)

    for col in data.columns:
        if col != "departement":
            data[col] = data[col].apply(to_float)

    return data

# ---------------- CALCULS KG ----------------
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
    seuil = max([s for s in seuils if s <= poids_total], default=None)
    if seuil is None:
        return np.nan
    prix_100 = row[str(seuil)]
    return prix_100 * (poids_arr / 100)

# ---------------- XPO ----------------
def calcul_palettes_facturees_xpo(poids_palettes):
    if len(poids_palettes) > 1:
        return float(len(poids_palettes))
    return 0.5 if poids_palettes[0] < 200 else 1.0

def trouver_colonne_xpo(row, total_palettes):
    for c in row.index:
        if isinstance(c, str) and "pal" in c.lower():
            nums = re.findall(r"[0-9.]+", c.replace(",", "."))
            if len(nums) >= 2:
                a = float(nums[0]); b = float(nums[1])
                if a >= 1.01:
                    if a < total_palettes <= b:
                        return c
                else:
                    if a <= total_palettes <= b:
                        return c
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

# ---------------- API PRINCIPALE ----------------
def compute_prices(departement, palettes, palette_parfaite,
                   df_geodis, df_dachser, df_kuehne, df_xpo, taxes):

    poids_total = sum(p["poids"] for p in palettes)
    poids_palettes = [p["poids"] for p in palettes]
    hauteur_max = max(p["H"] for p in palettes)

    results = []

    base = prix_transporteurs_kg(df_geodis, departement, poids_total)
    results.append(("GEODIS", base, appliquer_taxe(base, "GEODIS", taxes), f"Poids total {poids_total} kg"))

    base = prix_transporteurs_kg(df_dachser, departement, poids_total)
    results.append(("DACHSER", base, appliquer_taxe(base, "DACHSER", taxes), f"Poids total {poids_total} kg"))

    base = prix_kuehne(df_kuehne, departement, poids_total)
    results.append(("KUEHNE", base, appliquer_taxe(base, "KUEHNE", taxes), f"Poids total {poids_total} kg"))

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
