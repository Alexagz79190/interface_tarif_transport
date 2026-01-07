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

    if re.fullmatch(r"\d+\.0", s):  # ex "35.0"
        s = s.replace(".0", "")

    if re.fullmatch(r"\d{1,2}", s):  # ex "35"
        return s.zfill(2)

    m = re.search(r"(\d{1,2})", s)   # ex "Dpt 35", "(35)"
    if m:
        return m.group(1).zfill(2)

    return None


def parse_range(colname):
    """
    Parse des colonnes du type :
      - "0 à 4 kg"
      - "0.1-29.0 kg"
      - "100-199 kg"
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
        raise ValueError("TAXES/RFA: aucune colonne 'taux' trouvée")
    value_col = value_col[0]

    df[value_col] = df[value_col].apply(to_float)
    return dict(zip(df["Transporteurs"], df[value_col]))


def appliquer_taxe_et_rfa(prix_base, transporteur, taxes, rfa):
    """
    Prix final = prix * (1 + taxe%) * (1 - rfa%)
    """
    if pd.isna(prix_base):
        return np.nan

    t = taxes.get(transporteur.upper(), 0) or 0
    r = rfa.get(transporteur.upper(), 0) or 0
    return prix_base * (1 + t / 100) * (1 - r / 100)


# ============================================================
# CHECK LIMITES (poids / dimensions)
# ============================================================

def check_limits(transporteur, palettes, cfg):
    """
    Vérifie les limites décrites dans constraints.yaml.
    Retourne (True, "") si OK sinon (False, "raison")
    """
    limits = cfg.get("limits", {})
    if not limits:
        return True, ""

    # limites globales
    max_total_weight = limits.get("max_total_weight_kg", None)
    poids_total = sum(p["poids"] for p in palettes)

    if max_total_weight is not None and poids_total > max_total_weight:
        return False, f"{transporteur}: poids total > {max_total_weight} kg"

    # limites par palette
    max_weight_per_pallet = limits.get("max_weight_per_pallet_kg", None)
    max_L = limits.get("max_length_m", None)
    max_l = limits.get("max_width_m", None)
    max_H = limits.get("max_height_m", None)

    for i, p in enumerate(palettes):
        if max_weight_per_pallet is not None and p["poids"] > max_weight_per_pallet:
            return False, f"{transporteur}: palette {i+1} > {max_weight_per_pallet} kg"

        if max_L is not None and p["L"] / 100 > max_L:
            return False, f"{transporteur}: palette {i+1} longueur > {max_L} m"

        if max_l is not None and p["l"] / 100 > max_l:
            return False, f"{transporteur}: palette {i+1} largeur > {max_l} m"

        if max_H is not None and p["H"] / 100 > max_H:
            return False, f"{transporteur}: palette {i+1} hauteur > {max_H} m"

    return True, ""


# ============================================================
# PARSERS Google Sheets (données CLEAN)
# ============================================================

def _generic_load_sheet(df_raw):
    df = df_raw.copy()
    df.columns = df.iloc[0]
    df = df.iloc[1:].copy()

    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~pd.Index(df.columns).duplicated()].copy()
    df = df.dropna(how="all")

    return df


def load_geodis_from_sheet(df_raw):
    df = _generic_load_sheet(df_raw)

    df = df.rename(columns={df.columns[0]: "departement"})
    df["departement"] = df["departement"].apply(extract_dept)
    df = df[df["departement"].notna()].copy()
    df["departement"] = df["departement"].astype(str).str.zfill(2)

    for col in df.columns:
        if col != "departement":
            df[col] = df[col].apply(to_float)

    return df


def load_dachser_from_sheet(df_raw):
    df = _generic_load_sheet(df_raw)

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
    Format CLEAN attendu :
    1ère ligne = headers incluant "1-29 kg", "30-39 kg", etc.
    """
    df = _generic_load_sheet(df_raw)

    # trouver la colonne département
    dept_col = None
    for c in df.columns:
        if str(c).strip().lower() == "departement":
            dept_col = c
            break

    if dept_col is None:
        # fallback : 2e colonne
        dept_col = df.columns[1]

    df = df.rename(columns={dept_col: "departement"})
    df["departement"] = df["departement"].apply(extract_dept)
    df = df[df["departement"].notna()].copy()
    df["departement"] = df["departement"].astype(str).str.zfill(2)

    # conversion float uniquement sur colonnes tranches
    for col in df.columns:
        if col != "departement" and parse_range(col):
            df[col] = df[col].apply(to_float)

    return df


def load_xpo_from_sheet(df_raw):
    df = _generic_load_sheet(df_raw)

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
# PRIX TRANCHES KG (GEODIS / DACHSER / KUEHNE)
# ============================================================

def trouver_prix_forfait(row, poids):
    """
    <=100kg : prix forfaitaire
    """
    for col in row.index:
        r = parse_range(col)
        if r:
            a, b = r
            if a <= poids <= b:
                return row[col]
    return np.nan


def trouver_prix_100kg(row, poids, rounding_10kg=True):
    """
    >100kg : prix au 100kg
    """
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

    split_100 = cfg.get("split_100kg", True)
    rounding_10kg = cfg.get("rounding_10kg", True)

    # MULTI TRIP (ex 20 = 13 + 20)
    multi = cfg.get("multi_trip_dept", {})
    if dep in multi:
        total = 0.0
        for d in multi[dep]:
            d = str(d).zfill(2)
            r = df[df["departement"].astype(str).str.zfill(2) == d]
            if r.empty:
                return np.nan
            row = r.iloc[0]

            if split_100 and poids_total > 100:
                part = trouver_prix_100kg(row, poids_total, rounding_10kg)
            else:
                part = trouver_prix_forfait(row, poids_total)

            if pd.isna(part):
                return np.nan

            total += float(part)
        return total

    # NORMAL
    r = df[df["departement"].astype(str).str.zfill(2) == dep]
    if r.empty:
        return np.nan
    row = r.iloc[0]

    if split_100 and poids_total > 100:
        return trouver_prix_100kg(row, poids_total, rounding_10kg)

    return trouver_prix_forfait(row, poids_total)


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

    # format "0.01 pal-0.50 pal"
    for c in cols:
        nums = re.findall(r"[0-9.]+", c.replace(",", "."))
        if len(nums) >= 2:
            a, b = float(nums[0]), float(nums[1])
            if a <= total_palettes <= b:
                return c

    # format ".01 pal", ".51 pal", "1.01 pal"...
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

    for i, p in enumerate(palettes):
        if p["H"] > max_h:
            return np.nan, f"XPO ignoré : palette {i+1} hauteur > {max_h} cm"
        if p["poids"] > max_w:
            return np.nan, f"XPO ignoré : palette {i+1} poids > {max_w} kg"
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

    # ============================================================
    # GEODIS
    # ============================================================
    if not cfg_geodis.get("enabled", True):
        base = np.nan
        info = "GEODIS désactivé"
    else:
        ok, reason = check_limits("GEODIS", palettes, cfg_geodis)
        if not ok:
            base = np.nan
            info = reason
        else:
            base = prix_transporteurs_kg(df_geodis, departement, poids_total, cfg_geodis)
            info = f"Poids total {poids_total} kg"

    results.append((
        "GEODIS",
        base,
        appliquer_taxe_et_rfa(base, "GEODIS", taxes, rfa),
        info
    ))

    # ============================================================
    # DACHSER
    # ============================================================
    if not cfg_dachser.get("enabled", True):
        base = np.nan
        info = "DACHSER désactivé"
    else:
        ok, reason = check_limits("DACHSER", palettes, cfg_dachser)
        if not ok:
            base = np.nan
            info = reason
        else:
            base = prix_transporteurs_kg(df_dachser, departement, poids_total, cfg_dachser)

            fixed_fee = cfg_dachser.get("fixed_fee_eur", 0) or 0
            if not pd.isna(base):
                base = base + fixed_fee

            info = f"Poids total {poids_total} kg + forfait {fixed_fee}€"

    results.append((
        "DACHSER",
        base,
        appliquer_taxe_et_rfa(base, "DACHSER", taxes, rfa),
        info
    ))

    # ============================================================
    # KUEHNE
    # ============================================================
    if not cfg_kuehne.get("enabled", True):
        base = np.nan
        info = "KUEHNE désactivé"
    else:
        ok, reason = check_limits("KUEHNE", palettes, cfg_kuehne)
        if not ok:
            base = np.nan
            info = reason
        else:
            base = prix_transporteurs_kg(df_kuehne, departement, poids_total, cfg_kuehne)
            info = f"Poids total {poids_total} kg"

    results.append((
        "KUEHNE",
        base,
        appliquer_taxe_et_rfa(base, "KUEHNE", taxes, rfa),
        info
    ))

    # ============================================================
    # XPO
    # ============================================================
    if not cfg_xpo.get("enabled", True):
        base = np.nan
        info = "XPO désactivé"
    else:
        ok, reason = check_limits("XPO", palettes, cfg_xpo)
        if not ok:
            base = np.nan
            info = reason
        else:
            base, info = prix_xpo(df_xpo, departement, palettes, palette_parfaite, cfg_xpo)

    results.append((
        "XPO",
        base,
        appliquer_taxe_et_rfa(base, "XPO", taxes, rfa),
        info
    ))

    # ============================================================
    # FORMAT OUTPUT
    # ============================================================
    out = []
    for t, base, total, info in results:
        out.append({
            "Transporteur": t,
            "Prix_base": None if pd.isna(base) else round(float(base), 2),
            "Prix_taxe": None if pd.isna(total) else round(float(total), 2),
            "Info": info
        })

    return out
