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

    # cas 35.0
    if re.fullmatch(r"\d+\.0", s):
        s = s.replace(".0", "")

    # cas 35
    if re.fullmatch(r"\d{1,2}", s):
        return s.zfill(2)

    # cas Dpt 35 / (35) / 35 - XXX
    m = re.search(r"(\d{1,2})", s)
    if m:
        return m.group(1).zfill(2)

    return None


def parse_range(colname):
    """
    Parse une colonne du type '0 à 4 kg', '0.1-29.0 kg', '100-199 kg'
    => (min,max)
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
    Feuille type :
    Transporteurs | Taux taxe gasoil
    OU
    Transporteurs | Taux RFA
    """
    df = df_raw.copy()
    df.columns = df.iloc[0]
    df = df.iloc[1:].copy()
    df.columns = [str(c).strip() for c in df.columns]

    if "Transporteurs" not in df.columns:
        raise ValueError("TAXES/RFA: colonne 'Transporteurs' introuvable")

    df["Transporteurs"] = df["Transporteurs"].astype(str).str.strip().str.upper()

    value_col = [c for c in df.columns if "taux" in c.lower()]
    if not value_col:
        raise ValueError("TAXES/RFA: aucune colonne contenant 'taux' trouvée")
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

def _clean_df_first_row_as_header(df_raw):
    df = df_raw.copy()
    df.columns = df.iloc[0]
    df = df.iloc[1:].copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~pd.Index(df.columns).duplicated()].copy()
    df = df.dropna(how="all")
    return df


def load_geodis_from_sheet(df_raw):
    df = _clean_df_first_row_as_header(df_raw)

    df = df.rename(columns={df.columns[0]: "departement"})
    df["departement"] = df["departement"].apply(extract_dept)
    df = df[df["departement"].notna()].copy()
    df["departement"] = df["departement"].astype(str).str.zfill(2)

    for col in df.columns:
        if col != "departement":
            df[col] = df[col].apply(to_float)

    return df


def load_dachser_from_sheet(df_raw):
    df = _clean_df_first_row_as_header(df_raw)

    df = df.rename(columns={df.columns[0]: "departement"})
    df["departement"] = df["departement"].apply(extract_dept)
    df = df[df["departement"].notna()].copy()
    df["departement"] = df["departement"].astype(str).str.zfill(2)

    for col in df.columns:
        if col != "departement":
            df[col] = df[col].apply(to_float)

    return df


def load_kuehne_from_sheet(df_raw):
    """
    KUEHNE CLEAN attendu :
    - 1ere ligne = headers
    - colonnes poids = "1-29 kg", "30-39 kg", etc.
    """
    df = _clean_df_first_row_as_header(df_raw)

    # trouver la colonne departement
    dep_col = None
    for c in df.columns:
        if str(c).strip().lower() == "departement":
            dep_col = c
            break
    if dep_col is None:
        dep_col = df.columns[1]  # fallback

    df = df.rename(columns={dep_col: "departement"})
    df["departement"] = df["departement"].apply(extract_dept)
    df = df[df["departement"].notna()].copy()
    df["departement"] = df["departement"].astype(str).str.zfill(2)

    for col in df.columns:
        if col != "departement":
            if parse_range(col):
                df[col] = df[col].apply(to_float)

    return df


def load_xpo_from_sheet(df_raw):
    df = _clean_df_first_row_as_header(df_raw)

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
# CONTRAINTES (POIDS / DIMENSIONS)
# ============================================================

def check_limits(palettes, cfg, transporteur):
    limits = cfg.get("limits", {})

    max_total = limits.get("max_weight_total_kg")
    max_per = limits.get("max_weight_per_pallet_kg")
    max_L = limits.get("max_length_m")
    max_l = limits.get("max_width_m")
    max_H = limits.get("max_height_m")

    poids_total = sum(p["poids"] for p in palettes)

    # poids total
    if max_total is not None and poids_total > max_total:
        return False, f"{transporteur} ignoré : poids total > {max_total} kg"

    # poids par palette
    if max_per is not None:
        for i, p in enumerate(palettes):
            if p["poids"] > max_per:
                return False, f"{transporteur} ignoré : palette {i+1} > {max_per} kg"

    # dimensions
    for i, p in enumerate(palettes):
        if max_L is not None and p["L"] > max_L * 100:
            return False, f"{transporteur} ignoré : palette {i+1} longueur > {max_L} m"
        if max_l is not None and p["l"] > max_l * 100:
            return False, f"{transporteur} ignoré : palette {i+1} largeur > {max_l} m"
        if max_H is not None and p["H"] > max_H * 100:
            return False, f"{transporteur} ignoré : palette {i+1} hauteur > {max_H} m"

    return True, "OK"


# ============================================================
# PRIX TRANCHES KG
# ============================================================

def trouver_prix_tranche(row, poids):
    for col in row.index:
        r = parse_range(col)
        if r:
            a, b = r
            if a <= poids <= b:
                return row[col]
    return np.nan


def prix_transporteurs_kg(df, departement, poids_total, cfg):
    dep = str(departement).zfill(2)

    # multi-trip
    multi = cfg.get("multi_trip_dept", {})
    if dep in multi:
        total = 0.0
        for d in multi[dep]:
            d = str(d).zfill(2)
            r = df[df["departement"].astype(str).str.zfill(2) == d]
            if r.empty:
                return np.nan
            row = r.iloc[0]
            part = trouver_prix_tranche(row, poids_total)
            if pd.isna(part):
                return np.nan
            total += float(part)
        return total

    # normal
    r = df[df["departement"].astype(str).str.zfill(2) == dep]
    if r.empty:
        return np.nan

    row = r.iloc[0]
    return trouver_prix_tranche(row, poids_total)


# ============================================================
# XPO
# ============================================================

def _format_ok(L, l, allowed_formats):
    dims = tuple(sorted([int(L), int(l)]))
    allowed = {tuple(sorted(x)) for x in allowed_formats}
    return dims in allowed


def _is_half_pallet(p, cfg):
    half = cfg.get("half_pallet", {})
    if not half.get("enabled", True):
        return False
    return p["poids"] < half.get("max_weight_kg", 200)


def _palettes_facturees(palettes, cfg):
    if len(palettes) > 1 and cfg.get("billing", {}).get("no_half_when_multiple", True):
        return float(len(palettes))

    p = palettes[0]
    if _is_half_pallet(p, cfg) and cfg.get("half_pallet", {}).get("only_if_single_palette", True):
        return 0.5
    return 1.0


def trouver_colonne_xpo(row, total_palettes):
    cols = [c for c in row.index if isinstance(c, str) and "pal" in c.lower()]
    if not cols:
        return None

    # cas colonnes concaténées "0.01 pal-0.50 pal"
    for c in cols:
        nums = re.findall(r"[0-9.]+", c.replace(",", "."))
        if len(nums) >= 2:
            a = float(nums[0]); b = float(nums[1])
            if a <= total_palettes <= b:
                return c

    # cas colonnes simples "2.01 pal"
    values = []
    for c in cols:
        nums = re.findall(r"[0-9.]+", c.replace(",", "."))
        if nums:
            values.append((float(nums[0]), c))
    values = sorted(values, key=lambda x: x[0])

    for i in range(len(values)):
        start, col = values[i]
        end = values[i + 1][0] if i + 1 < len(values) else start + 1
        if start <= total_palettes < end:
            return col

    return None


def prix_xpo(df_xpo, departement, palettes, palette_parfaite, cfg):
    if not cfg.get("enabled", True):
        return np.nan, "XPO désactivé"

    dep = str(departement).zfill(2)

    if cfg.get("palette_parfaite_required", True) and not palette_parfaite:
        return np.nan, "XPO ignoré : palette parfaite obligatoire"

    allowed_formats = cfg.get("allowed_formats_cm", [])
    max_h = cfg.get("max_height_cm", 220)
    max_w = cfg.get("max_weight_full_pallet_kg", 1000)

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

def compute_prices(
    departement,
    palettes,
    palette_parfaite,
    df_geodis,
    df_dachser,
    df_kuehne,
    df_xpo,
    taxes,
    rfa,
    constraints=None
):
    if constraints is None:
        constraints = load_constraints("constraints.yaml")

    poids_total = sum(p["poids"] for p in palettes)

    cfg_geodis = constraints.get("GEODIS", {})
    cfg_dachser = constraints.get("DACHSER", {})
    cfg_kuehne = constraints.get("KUEHNE", {})
    cfg_xpo = constraints.get("XPO", {})

    results = []

    # ---------------- GEODIS
    ok, msg = check_limits(palettes, cfg_geodis, "GEODIS")
    if not ok:
        results.append(("GEODIS", np.nan, np.nan, msg))
    else:
        base = prix_transporteurs_kg(df_geodis, departement, poids_total, cfg_geodis)
        results.append(("GEODIS", base, appliquer_taxe_et_rfa(base, "GEODIS", taxes, rfa), f"Poids total {poids_total} kg"))

    # ---------------- DACHSER
    ok, msg = check_limits(palettes, cfg_dachser, "DACHSER")
    if not ok:
        results.append(("DACHSER", np.nan, np.nan, msg))
    else:
        base = prix_transporteurs_kg(df_dachser, departement, poids_total, cfg_dachser)
        results.append(("DACHSER", base, appliquer_taxe_et_rfa(base, "DACHSER", taxes, rfa), f"Poids total {poids_total} kg"))

    # ---------------- KUEHNE
    ok, msg = check_limits(palettes, cfg_kuehne, "KUEHNE")
    if not ok:
        results.append(("KUEHNE", np.nan, np.nan, msg))
    else:
        base = prix_transporteurs_kg(df_kuehne, departement, poids_total, cfg_kuehne)
        results.append(("KUEHNE", base, appliquer_taxe_et_rfa(base, "KUEHNE", taxes, rfa), f"Poids total {poids_total} kg"))

    # ---------------- XPO
    ok, msg = check_limits(palettes, cfg_xpo, "XPO")
    if not ok:
        results.append(("XPO", np.nan, np.nan, msg))
    else:
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
