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

    s = str(x).strip()

    # cas "35.0"
    if re.fullmatch(r"\d+\.0", s):
        s = s.replace(".0", "")

    # cas "35"
    if re.fullmatch(r"\d{1,2}", s):
        return s.zfill(2)

    # cas "Dpt 35", "(35)", "35 - XXX"
    m = re.search(r"(\d{1,2})", s)
    if m:
        return m.group(1).zfill(2)

    return None

def parse_range(colname):
    """
    Parse des colonnes du type '0 à 4 kg', '0.1-29.0 kg', '100 à 199 kg', etc.
    Renvoie (min,max) ou None
    """
    if not isinstance(colname, str):
        return None

    col = colname.lower().replace("kg", "").strip().replace(",", ".")

    m = re.search(r"([0-9.]+)\s*à\s*([0-9.]+)", col)
    if m:
        return float(m.group(1)), float(m.group(2))

    m = re.search(r"([0-9.]+)\s*-\s*([0-9.]+)", col)
    if m:
        return float(m.group(1)), float(m.group(2))

    return None


# ============================================================
# TAXES / RFA
# ============================================================

def load_taxes_from_sheet(df_raw):
    """
    df_raw contient déjà l'onglet chargé (taxe_go ou rfa).
    Format attendu :
      Transporteurs | Taux taxe gasoil
    OU
      Transporteurs | Taux RFA
    """
    df = df_raw.copy()
    df.columns = df.iloc[0]
    df = df.iloc[1:].copy()

    df.columns = [str(c).strip() for c in df.columns]
    df["Transporteurs"] = df["Transporteurs"].astype(str).str.strip().str.upper()

    value_col = [c for c in df.columns if "taux" in c.lower()]
    if not value_col:
        raise ValueError("TAXES: aucune colonne 'taux' trouvée")
    value_col = value_col[0]

    df[value_col] = df[value_col].apply(to_float)
    return dict(zip(df["Transporteurs"], df[value_col]))

def appliquer_taxe_et_rfa(prix_base, transporteur, taxes, rfa):
    if pd.isna(prix_base):
        return np.nan

    t = taxes.get(transporteur.upper(), 0) or 0
    r = rfa.get(transporteur.upper(), 0) or 0

    return prix_base * (1 + (t / 100)) * (1 - (r / 100))


# ============================================================
# PARSERS GOOGLE SHEETS (données propres)
# ============================================================

def load_geodis_from_sheet(df_raw):
    df = df_raw.copy()
    df.columns = df.iloc[0]
    df = df.iloc[1:].copy()

    df.columns = [str(c).strip() for c in df.columns]
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
    df.columns = df.iloc[0]
    df = df.iloc[1:].copy()

    df.columns = [str(c).strip() for c in df.columns]
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

def load_kuehne_from_sheet(df_raw):
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
    df = df_raw.copy()
    df.columns = df.iloc[0]
    df = df.iloc[1:].copy()

    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~pd.Index(df.columns).duplicated()].copy()
    df = df.dropna(how="all")

    if df.columns[0].lower() != "departement":
        df = df.rename(columns={df.columns[0]: "departement"})

    df["departement"] = df["departement"].apply(extract_dept)
    df = df[df["departement"].notna()].copy()
    df["departement"] = df["departement"].astype(str).str.zfill(2)

    for col in df.columns:
        if col != "departement":
            df[col] = df[col].apply(to_float)

    return df


# ============================================================
# PRIX TRANCHES KG (GEODIS / DACHSER)
# ============================================================

def trouver_prix_forfait(row, poids):
    for col in row.index:
        r = parse_range(col)
        if r:
            a, b = r
            if a <= poids <= b:
                return row[col]
    return np.nan

def trouver_prix_100kg(row, poids, rounding_10kg=True):
    poids_arr = arrondi_10kg(poids) if rounding_10kg else poids
    for col in row.index:
        r = parse_range(col)
        if r:
            a, b = r
            if a <= poids <= b:
                prix_100 = row[col]
                return prix_100 * (poids_arr / 100)
    return np.nan

def prix_transporteurs_kg(df, departement, poids_total, cfg):
    dep = str(departement).zfill(2)

    r = df[df["departement"].astype(str).str.zfill(2) == dep]
    if r.empty:
        return np.nan

    row = r.iloc[0]

    # règles config
    split_100 = cfg.get("split_100kg", True)
    rounding_10kg = cfg.get("rounding_10kg", True)

    if split_100 and poids_total > 100:
        return trouver_prix_100kg(row, poids_total, rounding_10kg=rounding_10kg)
    return trouver_prix_forfait(row, poids_total)


# ============================================================
# KUEHNE
# ============================================================

def prix_kuehne(df, departement, poids_total, cfg):
    dep = str(departement).zfill(2)
    r = df[df["departement"] == dep]
    if r.empty:
        return np.nan

    # contrainte max poids
    max_weight_cfg = cfg.get("max_weight_kg", None)
    if max_weight_cfg is not None and poids_total > max_weight_cfg:
        return np.nan

    row = r.iloc[0]
    seuils = sorted([int(c) for c in row.index if str(c).isdigit()])
    if not seuils:
        return np.nan

    # max grille
    seuil_max = max(seuils)
    if poids_total > seuil_max:
        return np.nan

    split_100 = cfg.get("split_100kg", True)
    rounding_10kg = cfg.get("rounding_10kg", True)

    # forfait <=100
    if poids_total <= 100 or not split_100:
        seuil = next((s for s in seuils if poids_total <= s), None)
        if seuil is None:
            return np.nan
        return row[str(seuil)]

    # au 100kg
    poids_arr = arrondi_10kg(poids_total) if rounding_10kg else poids_total
    seuil = max([s for s in seuils if s <= poids_total], default=None)
    if seuil is None:
        return np.nan

    prix_100 = row[str(seuil)]
    return prix_100 * (poids_arr / 100)


# ============================================================
# XPO
# ============================================================

def _format_ok(L, l, allowed_formats):
    dims = tuple(sorted([int(L), int(l)]))
    allowed = {tuple(sorted(x)) for x in allowed_formats}
    return dims in allowed

def _is_half_pallet(p, cfg):
    if not cfg.get("half_pallet", {}).get("enabled", True):
        return False
    return p["poids"] <= cfg["half_pallet"].get("max_weight_kg", 200)

def _palettes_facturees(palettes, cfg):
    # si plusieurs palettes => pas de demi si activé
    if len(palettes) > 1 and cfg.get("billing", {}).get("no_half_when_multiple", True):
        return float(len(palettes))

    # une seule palette
    p = palettes[0]
    if _is_half_pallet(p, cfg) and cfg.get("half_pallet", {}).get("only_if_single_palette", True):
        return 0.5
    return 1.0

def trouver_colonne_xpo(row, total_palettes):
    """
    Trouve la colonne correspondant à la tranche palette.
    Supports :
     - colonnes ".01 pal", ".51 pal", "1.01 pal", "2.01 pal", etc.
     - colonnes "0.01 pal-0.50 pal", "0.51 pal-1.00 pal", etc.
    """
    # cas colonnes propres : ".01 pal", ".51 pal", "1.01 pal", ...
    cols = [c for c in row.index if isinstance(c, str) and "pal" in c.lower()]

    if not cols:
        return None

    # cas 1 : colonnes format "X.XX pal- Y.YY pal"
    for c in cols:
        nums = re.findall(r"[0-9.]+", c.replace(",", "."))
        if len(nums) >= 2:
            a = float(nums[0]); b = float(nums[1])
            if a <= total_palettes <= b:
                return c

    # cas 2 : colonnes format "2.01 pal" => tranche [2.01 - 3.00[
    # on trie les colonnes par valeur
    values = []
    for c in cols:
        nums = re.findall(r"[0-9.]+", c.replace(",", "."))
        if nums:
            values.append((float(nums[0]), c))
    values = sorted(values, key=lambda x: x[0])

    for i in range(len(values)):
        start, col = values[i]
        end = values[i+1][0] if i+1 < len(values) else start + 1
        if start <= total_palettes < end:
            return col

    return None

def prix_xpo(df_xpo, departement, palettes, palette_parfaite, cfg):
    dep = str(departement).zfill(2)

    if not cfg.get("enabled", True):
        return np.nan, "XPO désactivé"

    if cfg.get("palette_parfaite_required", True) and not palette_parfaite:
        return np.nan, "XPO ignoré : palette parfaite obligatoire"

    max_h = cfg.get("max_height_cm", 220)
    max_w = cfg.get("max_weight_full_pallet_kg", 1000)

    allowed_formats = cfg.get("allowed_formats_cm", [])

    # vérifications palettes
    for i, p in enumerate(palettes):
        if p["H"] > max_h:
            return np.nan, f"XPO ignoré : palette {i+1} hauteur > {max_h} cm"
        if p["poids"] > max_w:
            return np.nan, f"XPO ignoré : palette {i+1} > {max_w} kg"
        if allowed_formats and not _format_ok(p["L"], p["l"], allowed_formats):
            return np.nan, f"XPO ignoré : palette {i+1} format {p['L']}x{p['l']} non accepté"

    total_pal = _palettes_facturees(palettes, cfg)

    r = df_xpo[df_xpo["departement"].astype(str).str.zfill(2) == dep]
    if r.empty:
        return np.nan, "XPO ignoré : département absent"

    row = r.iloc[0]

    col = trouver_colonne_xpo(row, total_pal)
    if col is None:
        return np.nan, f"XPO ignoré : aucune tranche pour {total_pal} palette(s)"

    return row[col], f"XPO : {total_pal} palette(s), tranche {col}"


# ============================================================
# API PRINCIPALE
# ============================================================

def compute_prices(departement, palettes, palette_parfaite,
                   df_geodis, df_dachser, df_kuehne, df_xpo,
                   taxes, rfa, constraints=None):

    if constraints is None:
        constraints = load_constraints("constraints.yaml")

    results = []

    poids_total = sum(p["poids"] for p in palettes)

    # -------- GEODIS
    cfg_geodis = constraints.get("GEODIS", {})
    base = prix_transporteurs_kg(df_geodis, departement, poids_total, cfg_geodis)
    results.append(("GEODIS", base, appliquer_taxe_et_rfa(base, "GEODIS", taxes, rfa), f"Poids total {poids_total} kg"))

    # -------- DACHSER
    cfg_dachser = constraints.get("DACHSER", {})
    base = prix_transporteurs_kg(df_dachser, departement, poids_total, cfg_dachser)
    results.append(("DACHSER", base, appliquer_taxe_et_rfa(base, "DACHSER", taxes, rfa), f"Poids total {poids_total} kg"))

    # -------- KUEHNE
    cfg_kuehne = constraints.get("KUEHNE", {})
    base = prix_kuehne(df_kuehne, departement, poids_total, cfg_kuehne)
    results.append(("KUEHNE", base, appliquer_taxe_et_rfa(base, "KUEHNE", taxes, rfa), f"Poids total {poids_total} kg"))

    # -------- XPO
    cfg_xpo = constraints.get("XPO", {})
    base, info = prix_xpo(df_xpo, departement, palettes, palette_parfaite, cfg_xpo)
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
