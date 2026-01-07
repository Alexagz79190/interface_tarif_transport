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
    Parse des colonnes du type :
    - '0 à 4 kg'
    - '0.1-29.0 kg'
    - '1-29 kg'
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

def check_limits(palettes, poids_total, cfg, transporteur):
    limits = cfg.get("limits", {})
    if not limits:
        return True, None

    # ------------------------
    # Poids total (si défini)
    # ------------------------
    max_total = limits.get("max_weight_total_kg")
    if max_total is not None and poids_total > max_total:
        return False, f"{transporteur} ignoré : poids total > {max_total} kg"

    # ------------------------
    # Poids par palette (si défini)
    # ------------------------
    max_per = limits.get("max_weight_per_pallet_kg")
    if max_per is not None:
        for i, p in enumerate(palettes):
            if p["poids"] > max_per:
                return False, f"{transporteur} ignoré : palette {i+1} > {max_per} kg"

    # ------------------------
    # Dimensions (max sur toutes palettes)
    # ------------------------
    max_L = max(p["L"] for p in palettes) / 100.0  # cm -> m
    max_l = max(p["l"] for p in palettes) / 100.0
    max_H = max(p["H"] for p in palettes) / 100.0

    if limits.get("max_length_m") is not None and max_L > limits["max_length_m"]:
        return False, f"{transporteur} ignoré : longueur > {limits['max_length_m']} m"

    if limits.get("max_width_m") is not None and max_l > limits["max_width_m"]:
        return False, f"{transporteur} ignoré : largeur > {limits['max_width_m']} m"

    if limits.get("max_height_m") is not None and max_H > limits["max_height_m"]:
        return False, f"{transporteur} ignoré : hauteur > {limits['max_height_m']} m"

    return True, None

# ============================================================
# TAXE + RFA
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

    if "Transporteurs" not in df.columns:
        raise ValueError("TAXES: colonne 'Transporteurs' introuvable")

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
# PARSERS GOOGLE SHEETS (DONNÉES CLEAN)
# ============================================================

def _basic_clean(df_raw):
    df = df_raw.copy()
    df.columns = df.iloc[0]
    df = df.iloc[1:].copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~pd.Index(df.columns).duplicated()].copy()
    df = df.dropna(how="all")
    return df


def load_geodis_from_sheet(df_raw):
    df = _basic_clean(df_raw)

    df = df.rename(columns={df.columns[0]: "departement"})
    df["departement"] = df["departement"].apply(extract_dept)
    df = df[df["departement"].notna()].copy()
    df["departement"] = df["departement"].astype(str).str.zfill(2)

    for col in df.columns:
        if col != "departement":
            df[col] = df[col].apply(to_float)

    return df


def load_dachser_from_sheet(df_raw):
    df = _basic_clean(df_raw)

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
      departement | 1-29 kg | 30-39 kg | ...
    """
    df = _basic_clean(df_raw)

    # détecter colonne departement
    dept_col = None
    for c in df.columns:
        if str(c).strip().lower() == "departement":
            dept_col = c
            break

    if dept_col is None:
        dept_col = df.columns[1]  # fallback

    df = df.rename(columns={dept_col: "departement"})
    df["departement"] = df["departement"].apply(extract_dept)
    df = df[df["departement"].notna()].copy()
    df["departement"] = df["departement"].astype(str).str.zfill(2)

    # conversion float seulement colonnes ranges
    for col in df.columns:
        if col != "departement" and parse_range(col):
            df[col] = df[col].apply(to_float)

    return df


def load_xpo_from_sheet(df_raw):
    df = _basic_clean(df_raw)

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
# CALCUL PRIX TRANCHES KG (GEODIS / DACHSER / KUEHNE)
# ============================================================

def trouver_prix_tranche(row, poids):
    """
    Va chercher la colonne dont la tranche contient le poids.
    Exemple: poids 85 => tranche 80-89 => prix direct
    """
    for col in row.index:
        r = parse_range(col)
        if r:
            a, b = r
            if a <= poids <= b:
                return row[col]
    return np.nan


def trouver_prix_tranche_100kg(row, poids, rounding_10kg=True):
    """
    Cas où la colonne contient un prix pour 100 kg (ou équivalent)
    -> extrapole en * (poids_arrondi/100)
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


def prix_transporteurs_kg(df, departement, poids_total, cfg=None):
    """
    Calcul standard pour GEODIS / DACHSER / KUEHNE sur tranches kg.
    cfg optionnel (contraintes YAML).
    """
    if cfg is None:
        cfg = {}

    dep = str(departement).zfill(2)

    split_100 = cfg.get("split_100kg", True)
    rounding_10kg = cfg.get("rounding_10kg", True)

    # ---- multi trajets : ex DACHSER 20 = 13 + 20
    multi = cfg.get("multi_trip_dept", {})
    if dep in multi:
        total = 0.0
        for d in multi[dep]:
            d = str(d).zfill(2)

            r = df[df["departement"].astype(str).str.zfill(2) == d]
            if r.empty:
                return np.nan

            row = r.iloc[0]

            part = (
                trouver_prix_tranche_100kg(row, poids_total, rounding_10kg)
                if split_100 and poids_total > 100
                else trouver_prix_tranche(row, poids_total)
            )

            if pd.isna(part):
                return np.nan

            total += float(part)

        return total

    # ---- normal
    r = df[df["departement"].astype(str).str.zfill(2) == dep]
    if r.empty:
        return np.nan

    row = r.iloc[0]

    if split_100 and poids_total > 100:
        return trouver_prix_tranche_100kg(row, poids_total, rounding_10kg)

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
    # plusieurs palettes => pas de demi
    if len(palettes) > 1 and cfg.get("billing", {}).get("no_half_when_multiple", True):
        return float(len(palettes))

    # une seule palette
    p = palettes[0]
    if _is_half_pallet(p, cfg) and cfg.get("half_pallet", {}).get("only_if_single_palette", True):
        return 0.5

    return 1.0


def trouver_colonne_xpo(row, total_palettes):
    """
    Support :
     - colonnes ".01 pal", ".51 pal", "1.01 pal", "2.01 pal", ...
     - colonnes "0.01 pal-0.50 pal"
    """
    cols = [c for c in row.index if isinstance(c, str) and "pal" in c.lower()]
    if not cols:
        return None

    # cas format "0.01-0.50"
    for c in cols:
        nums = re.findall(r"[0-9.]+", c.replace(",", "."))
        if len(nums) >= 2:
            a = float(nums[0]); b = float(nums[1])
            if a <= total_palettes <= b:
                return c

    # cas format ".01 pal"
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


def prix_xpo(df_xpo, departement, palettes, palette_parfaite, cfg=None):
    if cfg is None:
        cfg = {}

    dep = str(departement).zfill(2)

    if not cfg.get("enabled", True):
        return np.nan, "XPO désactivé"

    if cfg.get("palette_parfaite_required", True) and not palette_parfaite:
        return np.nan, "XPO ignoré : palette parfaite obligatoire"

    max_h = cfg.get("max_height_cm", 220)
    max_w_full = cfg.get("max_weight_full_pallet_kg", 1000)
    allowed_formats = cfg.get("allowed_formats_cm", [])

    # vérifs par palette
    for i, p in enumerate(palettes):
        if p["H"] > max_h:
            return np.nan, f"XPO ignoré : palette {i+1} hauteur > {max_h} cm"
        if p["poids"] > max_w_full:
            return np.nan, f"XPO ignoré : palette {i+1} > {max_w_full} kg"
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

    # ---------------- GEODIS ----------------
    ok, msg = check_limits(palettes, cfg_geodis, "GEODIS")
    if not ok:
        results.append(("GEODIS", np.nan, np.nan, msg))
    else:
        base = prix_transporteurs_kg(df_geodis, departement, poids_total, cfg_geodis)
        results.append(("GEODIS", base, appliquer_taxe_et_rfa(base, "GEODIS", taxes, rfa), f"Poids total {poids_total} kg"))

    # ---------------- DACHSER ----------------
    ok, msg = check_limits(palettes, cfg_dachser, "DACHSER")
    if not ok:
        results.append(("DACHSER", np.nan, np.nan, msg))
    else:
        base = prix_transporteurs_kg(df_dachser, departement, poids_total, cfg_dachser)
        results.append(("DACHSER", base, appliquer_taxe_et_rfa(base, "DACHSER", taxes, rfa), f"Poids total {poids_total} kg"))

    # ---------------- KUEHNE ----------------
    ok, msg = check_limits(palettes, cfg_kuehne, "KUEHNE")
    if not ok:
        results.append(("KUEHNE", np.nan, np.nan, msg))
    else:
        base = prix_transporteurs_kg(df_kuehne, departement, poids_total, cfg_kuehne)
        results.append(("KUEHNE", base, appliquer_taxe_et_rfa(base, "KUEHNE", taxes, rfa), f"Poids total {poids_total} kg"))

    # ---------------- XPO ----------------
    ok, msg = check_limits(palettes, cfg_xpo, "XPO")
    if not ok:
        results.append(("XPO", np.nan, np.nan, msg))
    else:
        base, info = prix_xpo(df_xpo, departement, palettes, palette_parfaite, cfg_xpo)
        results.append(("XPO", base, appliquer_taxe_et_rfa(base, "XPO", taxes, rfa), info))

    # ---------------- FORMAT OUTPUT ----------------
    out = []
    for t, base, total, info in results:
        out.append({
            "Transporteur": t,
            "Prix_base": None if pd.isna(base) else round(float(base), 2),
            "Prix_taxe": None if pd.isna(total) else round(float(total), 2),
            "Info": info
        })

    return out
