import pandas as pd
import numpy as np
import math
import re

def to_float(x):
    if pd.isna(x):
        return np.nan
    x = str(x).replace("€", "").replace(" ", "").replace(",", ".")
    try:
        return float(x)
    except:
        return np.nan

def arrondi_10kg(poids):
    return math.ceil(poids / 10) * 10

def extract_dept(x):
    if pd.isna(x):
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
def load_taxes(path):
    df = pd.read_csv(path, sep=None, engine="python")
    df.columns = [c.strip() for c in df.columns]
    df["Transporteurs"] = df["Transporteurs"].astype(str).str.strip().str.upper()
    df["Taux taxe gasoil"] = df["Taux taxe gasoil"].apply(to_float)
    return dict(zip(df["Transporteurs"], df["Taux taxe gasoil"]))

def appliquer_taxe(prix_base, transporteur, taxes):
    if pd.isna(prix_base):
        return np.nan
    taux = taxes.get(transporteur.upper(), 0)
    return prix_base * (1 + (taux / 100))

# ---------------- LOADERS ----------------
def load_geodis(path):
    df = pd.read_excel(path)
    headers = df.iloc[9].tolist()
    data = df.iloc[11:].copy()
    data.columns = headers
    data = data.loc[:, ~data.columns.duplicated()]

    dept_col = data.columns[1]
    data = data.rename(columns={dept_col: "departement"})
    data["departement"] = data["departement"].apply(extract_dept)

    for col in data.columns:
        if col != "departement":
            data[col] = data[col].apply(to_float)
    return data

def load_dachser(path):
    df = pd.read_excel(path)
    debuts = df.iloc[3].tolist()
    fins = df.iloc[4].tolist()

    data = df.iloc[10:].copy()
    data = data.loc[:, ~data.columns.duplicated()]
    data = data.rename(columns={df.columns[0]: "departement"})
    data["departement"] = data["departement"].astype(str).str.zfill(2)

    col_map = {}
    for idx in range(1, len(df.columns)):
        d = debuts[idx]
        f = fins[idx]
        if pd.notna(d) and pd.notna(f):
            col_map[df.columns[idx]] = f"{d}-{f} kg"

    data = data.rename(columns=col_map)
    keep_cols = ["departement"] + list(col_map.values())
    data = data[keep_cols]

    for col in data.columns:
        if col != "departement":
            data[col] = data[col].apply(to_float)
    return data

def load_kuehne(path):
    raw = pd.read_csv(path, sep=";", encoding="utf-8", header=None)
    header1 = raw.iloc[0].tolist()
    cols = ["Pays","departement","Destination","Difficulte","Poids_reel"] + header1[5:]
    data = raw.iloc[2:].copy()
    data.columns = cols

    data["departement"] = data["departement"].astype(str).str.strip()
    data = data[data["departement"].str.match(r"^\d{1,2}$", na=False)]
    data["departement"] = data["departement"].str.zfill(2)

    for col in data.columns:
        if col not in ["Pays","departement","Destination","Difficulte","Poids_reel"]:
            data[col] = data[col].apply(to_float)
    return data

def load_xpo(path):
    df = pd.read_excel(path)
    deb = df.iloc[13].tolist()
    fin = df.iloc[14].tolist()

    data = df.iloc[18:].copy()
    data = data.loc[:, ~data.columns.duplicated()]
    data = data.rename(columns={df.columns[0]: "departement"})
    data["departement"] = data["departement"].apply(extract_dept)

    col_map = {}
    for idx in range(1, 12):
        if pd.notna(deb[idx]) and pd.notna(fin[idx]):
            col_map[df.columns[idx]] = f"{deb[idx]} pal-{fin[idx]} pal"

    data = data.rename(columns=col_map)
    keep_cols = ["departement"] + list(col_map.values())
    data = data[keep_cols]

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
    """
    Règle XPO :
    - Si >1 palette : on ignore les demi => palettes facturées = nb palettes physiques
    - Si 1 palette :
        <200kg => 0.5
        >=200kg => 1
    """
    if len(poids_palettes) > 1:
        return float(len(poids_palettes))
    p = poids_palettes[0]
    return 0.5 if p < 200 else 1.0

def trouver_colonne_xpo(row, total_palettes):
    """
    Tranches :
    0.01-0.50 (demi)
    0.51-1.00 (1)
    1.01-2.00 (2)
    2.01-3.00 (3)
    ...
    """
    for c in row.index:
        if isinstance(c, str) and "pal" in c.lower():
            nums = re.findall(r"[0-9.]+", c.replace(",", "."))
            if len(nums) >= 2:
                a = float(nums[0]); b = float(nums[1])
                # borne basse exclue à partir de 1.01
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

    return row[col], f"XPO : {total_pal} palette(s) facturée(s), tranche {col}"

# ---------------- API PRINCIPALE ----------------
def compute_prices(departement, palettes, palette_parfaite, paths):
    """
    palettes: liste de dicts [{"poids":..., "L":..., "l":..., "H":...}, ...]
    """
    df_geodis = load_geodis(paths["GEODIS"])
    df_dachser = load_dachser(paths["DACHSER"])
    df_kuehne = load_kuehne(paths["KUEHNE"])
    df_xpo = load_xpo(paths["XPO"])
    taxes = load_taxes(paths["TAXE_GO"])

    poids_total = sum(p["poids"] for p in palettes)
    poids_palettes = [p["poids"] for p in palettes]
    hauteur_max = max(p["H"] for p in palettes)  # contrainte XPO

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
        if pd.notna(total):
            out.append({"Transporteur": t, "Prix_base": round(float(base), 2), "Prix_taxe": round(float(total), 2), "Info": info})
        else:
            out.append({"Transporteur": t, "Prix_base": None, "Prix_taxe": None, "Info": info})
    return out
