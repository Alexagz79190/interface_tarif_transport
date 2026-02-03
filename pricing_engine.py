import pandas as pd
import numpy as np
import math
import re
from config_loader import load_constraints
from datetime import datetime, date
from zoneinfo import ZoneInfo



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

def is_in_period_mmdd(start_mmdd: str, end_mmdd: str, tz="Europe/Paris") -> bool:
    today = datetime.now(ZoneInfo(tz)).date()
    y = today.year
    start_m, start_d = map(int, start_mmdd.split("-"))
    end_m, end_d = map(int, end_mmdd.split("-"))

    start = date(y, start_m, start_d)
    end = date(y, end_m, end_d)

    # cas normal (05-01 -> 08-31)
    if start <= end:
        return start <= today <= end

    # cas période qui traverse l'année (ex 11-15 -> 02-15)
    return today >= start or today <= end

def count_europe_palettes(palettes):
    nb_europe = sum(1 for p in palettes if bool(p.get("is_europe", False)))
    return nb_europe


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

    # colonne difficulté (colonne D fallback)
    diff_col = None
    for c in df.columns:
        name = str(c).strip().lower()
        if name in ("difficulte", "difficulté"):
            diff_col = c
            break
    if diff_col is None and len(df.columns) >= 4:
        diff_col = df.columns[3]

    if diff_col is not None:
        df = df.rename(columns={diff_col: "difficulte"})
        df["difficulte"] = df["difficulte"].apply(lambda x: "" if pd.isna(x) else str(x).strip())
        df["difficulte"] = df["difficulte"].replace("nan", "")
    else:
        df["difficulte"] = ""

    # conversion float uniquement sur colonnes tranches kg
    for col in df.columns:
        if col not in ("departement", "difficulte") and parse_range(col):
            df[col] = df[col].apply(to_float)

    return df


def load_kuehne_from_sheet(df_raw):
    """
    Format CLEAN attendu :
    - Colonne département
    - Colonne difficulté (colonne D) : vide = standard, non vide = difficile
    - Colonnes tranches poids : "1-29 kg", "30-39 kg", etc.
    """
    df = _generic_load_sheet(df_raw)

    # ------------------------------------------------------------
    # Département
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # Difficulté (colonne D du sheet)
    # ------------------------------------------------------------
    diff_col = None
    for c in df.columns:
        name = str(c).strip().lower()
        if name in ("difficulte", "difficulté"):
            diff_col = c
            break

    # fallback strict : colonne D (index 3)
    if diff_col is None and len(df.columns) >= 4:
        diff_col = df.columns[3]

    if diff_col is not None:
        df = df.rename(columns={diff_col: "difficulte"})
        # conversion safe : gère int/float/None
        df["difficulte"] = df["difficulte"].apply(lambda x: "" if pd.isna(x) else str(x).strip())
        # au cas où ça remonte "nan"
        df["difficulte"] = df["difficulte"].replace("nan", "")
    else:
        df["difficulte"] = ""

    # ------------------------------------------------------------
    # Conversion float UNIQUEMENT sur colonnes tranches kg
    # ------------------------------------------------------------
    for col in df.columns:
        if col not in ("departement", "difficulte") and parse_range(col):
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
# ZONE URBAINE
# ============================================================

def _normalize_zone_label(z):
    if z is None:
        return None
    s = str(z).strip().upper()
    # attend "ZONE A" / "ZONE B" ou "A"/"B"
    if "A" in s and "ZONE" in s:
        return "A"
    if "B" in s and "ZONE" in s:
        return "B"
    if s in ("A", "B"):
        return s
    m = re.search(r"\b([AB])\b", s)
    return m.group(1) if m else None


def _parse_cp_cell(cell):
    """
    Renvoie:
      - cps: set de CP explicites
      - ranges: list de tuples (start,end) inclusifs
      - all_dept: bool (Tous codes postaux)
    """
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return {"cps": set(), "ranges": [], "all_dept": False}

    s = str(cell).strip()
    s_up = s.upper()

    if "TOUS" in s_up and "CODE" in s_up and "POST" in s_up:
        return {"cps": set(), "ranges": [], "all_dept": True}

    # Plage type "De 35000 à 35999" ou "35000-35999"
    m = re.search(r"(\d{5})\s*(?:A|À|-)\s*(\d{5})", s_up)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            a, b = b, a
        return {"cps": set(), "ranges": [(a, b)], "all_dept": False}

    # Liste séparée par virgules
    cps = set()
    for token in re.split(r"[,;/\s]+", s):
        token = token.strip()
        if re.fullmatch(r"\d{5}", token):
            cps.add(token)

    return {"cps": cps, "ranges": [], "all_dept": False}


def load_geodis_zone_urbaine_from_sheet(df_zone_urbaine_raw):
    """
    Attendu: colonnes:
      Département | Secteur | CP | Type de Zone
    Renvoie:
      cp_to_zone: dict cp->"A"/"B"
      ranges: list((start,end,zone))  (sans expansion)
      dept_prefix_zone: dict dept->"A"/"B" (Tous codes postaux)
    """
    df = _generic_load_sheet(df_zone_urbaine_raw)

    # normalisation colonnes
    col_norm = {c: str(c).strip().lower() for c in df.columns}
    df = df.rename(columns=col_norm)

    # repérage colonnes
    dept_col = next((c for c in df.columns if "departement" in c or "département" in c), df.columns[0])
    cp_col = next((c for c in df.columns if c == "cp" or "code postal" in c or "code_postal" in c), df.columns[2] if len(df.columns) >= 3 else df.columns[1])
    zone_col = next((c for c in df.columns if "zone" in c), df.columns[-1])

    cp_to_zone = {}
    ranges = []
    dept_prefix_zone = {}

    for _, r in df.iterrows():
        dept = extract_dept(r.get(dept_col))
        zone = _normalize_zone_label(r.get(zone_col))
        if not dept or zone not in ("A", "B"):
            continue

        parsed = _parse_cp_cell(r.get(cp_col))

        if parsed["all_dept"]:
            dept_prefix_zone[dept] = zone
            continue

        for cp in parsed["cps"]:
            cp_to_zone[cp] = zone

        for a, b in parsed["ranges"]:
            ranges.append((a, b, zone))

    return cp_to_zone, ranges, dept_prefix_zone

def _normalize_type_label(t):
    if t is None:
        return None
    s = str(t).strip().upper()
    if "URB" in s:
        return "URBAIN"
    if "SAIS" in s:
        return "SAISONNIER"
    return None


def load_kuehne_zone_urbaine_from_sheet(df_raw):
    """
    Colonnes attendues:
      Département | Secteur | CP | Type
    Type = Urbain / Saisonnier
    Retour:
      cp_to_type: dict(cp -> "URBAIN"/"SAISONNIER")
      ranges: list((start,end,type))
      dept_prefix_type: dict(dept -> "URBAIN"/"SAISONNIER")  (Tous codes postaux)
    """
    df = _generic_load_sheet(df_raw)

    col_norm = {c: str(c).strip().lower() for c in df.columns}
    df = df.rename(columns=col_norm)

    dept_col = next((c for c in df.columns if "departement" in c or "département" in c), df.columns[0])
    cp_col   = next((c for c in df.columns if c == "cp" or "code postal" in c or "code_postal" in c), df.columns[2])
    type_col = next((c for c in df.columns if "type" in c), df.columns[-1])

    cp_to_type = {}
    ranges = []
    dept_prefix_type = {}

    for _, r in df.iterrows():
        dept = extract_dept(r.get(dept_col))
        typ  = _normalize_type_label(r.get(type_col))
        if not dept or typ not in ("URBAIN", "SAISONNIER"):
            continue

        parsed = _parse_cp_cell(r.get(cp_col))

        if parsed["all_dept"]:
            dept_prefix_type[dept] = typ
            continue

        for cp in parsed["cps"]:
            cp_to_type[cp] = typ

        for a, b in parsed["ranges"]:
            ranges.append((a, b, typ))

    return cp_to_type, ranges, dept_prefix_type


def kuehne_get_type(code_postal: str, departement: str, cp_to_type: dict, ranges: list, dept_prefix_type: dict):
    cp = "" if code_postal is None else str(code_postal).strip()
    cp = re.sub(r"\.0$", "", cp)
    if re.fullmatch(r"\d{1,5}", cp):
        cp = cp.zfill(5)

    if cp in cp_to_type:
        return cp_to_type[cp]

    if re.fullmatch(r"\d{5}", cp):
        cp_int = int(cp)
        for a, b, t in ranges:
            if a <= cp_int <= b:
                return t

    dep = str(departement).zfill(2)
    t = dept_prefix_type.get(dep)
    if t and cp.startswith(dep):
        return t

    return None


def geodis_get_urban_zone(code_postal: str, departement: str, cp_to_zone: dict, ranges: list, dept_prefix_zone: dict):
    # normaliser CP
    cp = "" if code_postal is None else str(code_postal).strip()
    cp = re.sub(r"\.0$", "", cp)
    if re.fullmatch(r"\d{1,5}", cp):
        cp = cp.zfill(5)

    # priorité 1 : CP explicite
    if cp in cp_to_zone:
        return cp_to_zone[cp]

    # priorité 2 : plages
    if re.fullmatch(r"\d{5}", cp):
        cp_int = int(cp)
        for a, b, z in ranges:
            if a <= cp_int <= b:
                return z

    # priorité 3 : "Tous codes postaux" => préfixe dept
    dep = str(departement).zfill(2)
    z = dept_prefix_zone.get(dep)
    if z and cp.startswith(dep):
        return z

    return None

def geodis_urban_fee(poids_total: float, zone: str, cfg_geodis: dict):
    zu = cfg_geodis.get("zone_urbaine", {})
    if not zu.get("enabled", True):
        return 0.0

    fees = zu.get("fees_eur", {})
    fz = fees.get("zone_a", {}) if zone == "A" else fees.get("zone_b", {}) if zone == "B" else {}
    if not fz:
        return 0.0

    if poids_total is None or pd.isna(poids_total) or poids_total <= 0:
        return 0.0
    if poids_total <= 30:
        return float(fz.get("0_30", 0) or 0)
    if poids_total <= 100:
        return float(fz.get("30_100", 0) or 0)
    return float(fz.get("100_plus", 0) or 0)


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
# FONCTION ZONE DIFFICILE
# ============================================================

def load_zone_set_from_sheet(df_zone_raw) -> set:
    # 1) On normalise le sheet comme les autres (1ère ligne = header)
    df = _generic_load_sheet(df_zone_raw)

    # 2) Normalisation des noms de colonnes (MAJ, trim, suppression espaces/_)
    def _norm_col(c: str) -> str:
        c = str(c).strip().upper()
        c = c.replace("É", "E").replace("È", "E").replace("Ê", "E")
        c = c.replace("À", "A").replace("Â", "A")
        c = c.replace("Ù", "U").replace("Û", "U")
        c = c.replace("Ç", "C")
        c = re.sub(r"[\s\-_]+", "", c)  # enlève espaces, tirets, underscores
        return c

    col_map = {c: _norm_col(c) for c in df.columns}
    df = df.rename(columns=col_map)

    # 3) Détection robuste de la colonne code postal
    cp_col = None
    if "CODEPOSTAL" in df.columns:
        cp_col = "CODEPOSTAL"
    else:
        # fallback : trouver une colonne contenant "CODE" et "POSTAL"
        for c in df.columns:
            if "CODE" in c and "POSTAL" in c:
                cp_col = c
                break
        # fallback 2 : première colonne
        if cp_col is None and len(df.columns) >= 1:
            cp_col = df.columns[0]

    # 4) Nettoyage + set
    df[cp_col] = df[cp_col].apply(lambda x: "" if pd.isna(x) else str(x).strip())
    df[cp_col] = df[cp_col].str.replace(r"\.0$", "", regex=True)  # 35000.0 -> 35000

    df = df[df[cp_col].str.fullmatch(r"\d{5}", na=False)]
    return set(df[cp_col].tolist())

# ============================================================
# GEODIS - ZONE URBAINE
# ============================================================

def _normalize_zone_label(z):
    if z is None:
        return None
    s = str(z).strip().upper()
    if s in ("A", "ZONE A"):
        return "A"
    if s in ("B", "ZONE B"):
        return "B"
    m = re.search(r"\b([AB])\b", s)
    return m.group(1) if m else None


def _parse_cp_cell(cell):
    """
    CP:
      - "35000,35200"
      - "De 35000 à 35999"
      - "35000-35999"
      - "Tous codes postaux"
    """
    if cell is None or (isinstance(cell, float) and pd.isna(cell)):
        return {"cps": set(), "ranges": [], "all_dept": False}

    s = str(cell).strip()
    s_up = s.upper()

    if "TOUS" in s_up and "CODE" in s_up:
        return {"cps": set(), "ranges": [], "all_dept": True}

    m = re.search(r"(\d{5})\s*(?:A|À|-)\s*(\d{5})", s_up)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            a, b = b, a
        return {"cps": set(), "ranges": [(a, b)], "all_dept": False}

    cps = set()
    for t in re.split(r"[,;/\s]+", s):
        if re.fullmatch(r"\d{5}", t):
            cps.add(t)

    return {"cps": cps, "ranges": [], "all_dept": False}


def load_geodis_zone_urbaine_from_sheet(df_raw):
    """
    Colonnes attendues:
      Département | Secteur | CP | Type de Zone
    Retour:
      cp_to_zone: dict(cp -> "A"/"B")
      ranges: list((start,end,zone))
      dept_prefix_zone: dict(dept -> "A"/"B")
    """
    df = _generic_load_sheet(df_raw)
    df.columns = [str(c).strip().lower() for c in df.columns]

    dept_col = next((c for c in df.columns if "departement" in c or "département" in c), df.columns[0])
    cp_col = next((c for c in df.columns if c == "cp" or "code postal" in c), df.columns[2])
    zone_col = next((c for c in df.columns if "zone" in c), df.columns[-1])

    cp_to_zone = {}
    ranges = []
    dept_prefix_zone = {}

    for _, r in df.iterrows():
        dept = extract_dept(r.get(dept_col))
        zone = _normalize_zone_label(r.get(zone_col))
        if not dept or zone not in ("A", "B"):
            continue

        parsed = _parse_cp_cell(r.get(cp_col))

        if parsed["all_dept"]:
            dept_prefix_zone[dept] = zone
            continue

        for cp in parsed["cps"]:
            cp_to_zone[cp] = zone

        for a, b in parsed["ranges"]:
            ranges.append((a, b, zone))

    return cp_to_zone, ranges, dept_prefix_zone

# ============================================================
# FONCTION COEFICIENT TAXE ZONE DIFFICILE XPO 
# ============================================================

def poids_taxe_palette_xpo(L_cm: float, l_cm: float) -> int:
    a, b = sorted([int(L_cm), int(l_cm)])
    mapping = {
        (80, 120): 400,
        (100, 120): 600,
        (120, 120): 800,
    }
    # None = format non géré => on bloque XPO
    return mapping.get((a, b), None)


def poids_taxe_total_xpo(palettes) -> int:
    total = 0
    for p in palettes:
        pt = poids_taxe_palette_xpo(p["L"], p["l"])
        if pt is None:
            return None
        total += pt
    return total

# ============================================================
# FONCTION COEFICIENT TAXE ZONE DIFFICILE XPO 
# ============================================================

def _normalize_kuehne_type(t):
    if t is None:
        return None
    s = str(t).strip().upper()
    if "URB" in s:
        return "URBAIN"
    if "SAIS" in s:
        return "SAISONNIER"
    return None


def load_kuehne_zone_urbaine_from_sheet(df_raw):
    """
    Colonnes attendues:
      Département | Secteur | CP | Type
    Retour:
      cp_to_type: dict(cp -> "URBAIN"/"SAISONNIER")
      ranges: list((start,end,type))
      dept_prefix_type: dict(dept -> "URBAIN"/"SAISONNIER")
    """
    df = _generic_load_sheet(df_raw)
    df.columns = [str(c).strip().lower() for c in df.columns]

    dept_col = next((c for c in df.columns if "departement" in c or "département" in c), df.columns[0])
    cp_col   = next((c for c in df.columns if c == "cp" or "code postal" in c or "code_postal" in c), df.columns[2])
    type_col = next((c for c in df.columns if "type" in c), df.columns[-1])

    cp_to_type = {}
    ranges = []
    dept_prefix_type = {}

    for _, r in df.iterrows():
        dept = extract_dept(r.get(dept_col))
        t = _normalize_kuehne_type(r.get(type_col))
        if not dept or t not in ("URBAIN", "SAISONNIER"):
            continue

        parsed = _parse_cp_cell(r.get(cp_col))

        if parsed["all_dept"]:
            dept_prefix_type[dept] = t
            continue

        for cp in parsed["cps"]:
            cp_to_type[cp] = t

        for a, b in parsed["ranges"]:
            ranges.append((a, b, t))

    return cp_to_type, ranges, dept_prefix_type


def kuehne_get_type(code_postal: str, departement: str, cp_to_type: dict, ranges: list, dept_prefix_type: dict):
    # normaliser CP
    cp = "" if code_postal is None else str(code_postal).strip()
    cp = re.sub(r"\.0$", "", cp)
    if re.fullmatch(r"\d{1,5}", cp):
        cp = cp.zfill(5)

    # priorité 1 : CP explicite
    if cp in cp_to_type:
        return cp_to_type[cp]

    # priorité 2 : plages
    if re.fullmatch(r"\d{5}", cp):
        cp_int = int(cp)
        for a, b, t in ranges:
            if a <= cp_int <= b:
                return t

    # priorité 3 : "Tous codes postaux" => préfixe dept
    dep = str(departement).zfill(2)
    t = dept_prefix_type.get(dep)  # ✅ ici .get sur dict, PAS sur list
    if t and cp.startswith(dep):
        return t

    return None

# ============================================================
# API PRINCIPALE
# ============================================================

def compute_prices(
    departement,
    code_postal: str,
    geodis_zone_difficile: set,
    geodis_cp_to_zone: dict,
    geodis_ranges: list,
    geodis_dept_prefix_zone: dict,
    kuehne_zone: set,
    kuehne_cp_to_type: dict,
    kuehne_ranges: list,
    kuehne_dept_prefix_type: dict,
    dachser_zone: set,
    xpo_acces_difficile: set,
    xpo_grande_ville: set,  
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
    nb_europe = count_europe_palettes(palettes)


    cfg_geodis = constraints.get("GEODIS", {})
    cfg_dachser = constraints.get("DACHSER", {})
    cfg_kuehne_raw = constraints.get("KUEHNE", {})
    cfg_kuehne = cfg_kuehne_raw[0] if isinstance(cfg_kuehne_raw, list) else cfg_kuehne_raw
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

            fixed_fee = float(cfg_geodis.get("fixed_fee_eur", 0) or 0)

            # zone difficile
            zd_cfg = cfg_geodis.get("zone_difficile", {})
            zd_enabled = zd_cfg.get("enabled", True)
            zd_fee = float(zd_cfg.get("fee_eur", 0) or 0)
            is_zone_difficile = (zd_enabled and (code_postal in geodis_zone_difficile))

            # zone urbaine
            urban_zone = geodis_get_urban_zone(
                code_postal, departement,
                geodis_cp_to_zone, geodis_ranges, geodis_dept_prefix_zone
            )
            urban_fee = geodis_urban_fee(poids_total, urban_zone, cfg_geodis)

            # ✅ Europe par palette (si configuré)
            europe_fee = float(cfg_geodis.get("europe_pallet_fee_eur_per_pallet", 0) or 0)
            surcharge_europe = 0.0
            if europe_fee > 0 and nb_europe > 0:
                surcharge_europe = europe_fee * float(nb_europe)

            added = fixed_fee + (zd_fee if is_zone_difficile else 0) + urban_fee + surcharge_europe
            if not pd.isna(base):
                base = base + added

            info = (
                f"Poids total {poids_total} kg"
                f" | forfait={fixed_fee}€"
                f" | zone difficile={is_zone_difficile} (+{zd_fee if is_zone_difficile else 0}€)"
                f" | zone urbaine={urban_zone} (+{round(urban_fee,2)}€)"
            )
            if surcharge_europe > 0:
                info += f" | pal_europe=+{round(surcharge_europe,2)}€ ({nb_europe}x)"

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
            is_zone_difficile = code_postal in dachser_zone
            fixed_fee = cfg_dachser.get("fixed_fee_eur", 0) or 0
            zone_fee = cfg_dachser.get("zone_difficile_fee_eur", 0) or 0

            # ------------------------------------------------------------
            # Helper: calcule le prix Dachser pour UN département (part)
            # ------------------------------------------------------------
            def _dachser_part_for_dept(dep_code: str, zone_difficile: bool):
                dep_code = str(dep_code).zfill(2)

                dfd = df_dachser.copy()
                dfd["departement"] = dfd["departement"].astype(str).str.zfill(2)
                dfd = dfd[dfd["departement"] == dep_code]

                if dfd.empty:
                    return np.nan

                # Choisir la bonne ligne selon difficulté (vide vs non vide)
                row = dfd.iloc[0]
                if "difficulte" in dfd.columns:
                    diff = dfd["difficulte"].apply(lambda x: "" if pd.isna(x) else str(x).strip())
                    has_diff = diff.ne("") & diff.ne("nan")

                    dfd2 = dfd[has_diff] if zone_difficile else dfd[~has_diff]
                    if not dfd2.empty:
                        row = dfd2.iloc[0]

                # Calcul tranches kg
                if cfg_dachser.get("split_100kg", True) and poids_total > 100:
                    return trouver_prix_100kg(row, poids_total, cfg_dachser.get("rounding_10kg", True))
                else:
                    return trouver_prix_forfait(row, poids_total)

            # ------------------------------------------------------------
            # MULTI TRIP (ex: dep 20 = dep 13 + dep 20)
            # ------------------------------------------------------------
            dep = str(departement).zfill(2)
            multi = cfg_dachser.get("multi_trip_dept", {})

            info_multi = None

            if dep in multi:
                total = 0.0
                parts = []
                for d in multi[dep]:
                    part = _dachser_part_for_dept(d, is_zone_difficile)
                    if pd.isna(part):
                        base = np.nan
                        info = f"DACHSER ignoré : département {str(d).zfill(2)} absent ou tranche non trouvée"
                        break
                    total += float(part)
                    parts.append(f"{str(d).zfill(2)}={round(float(part),2)}€")
                else:
                    base = total
                    info_multi = f"multi-trip {dep}=(" + " + ".join(parts) + ")"
            else:
                base = _dachser_part_for_dept(dep, is_zone_difficile)
                if pd.isna(base):
                    info = "DACHSER ignoré : département absent"

            # ------------------------------------------------------------
            # Ajout des frais (1 seule fois)
            # ------------------------------------------------------------
            if not pd.isna(base):
                added = fixed_fee + (zone_fee if is_zone_difficile else 0)

                # ✅ Europe par palette (si configuré)
                europe_fee = float(cfg_dachser.get("europe_pallet_fee_eur_per_pallet", 0) or 0)
                surcharge_europe = 0.0
                if europe_fee > 0 and nb_europe > 0:
                    surcharge_europe = europe_fee * float(nb_europe)
                    added += surcharge_europe

                base = base + added

                info = (
                    f"Poids total {poids_total} kg | "
                    f"zone difficile={is_zone_difficile} | "
                    f"forfait={fixed_fee}€ | "
                    f"sup zone={zone_fee if is_zone_difficile else 0}€"
                )

                # ✅ ajoute l’info Europe
                if surcharge_europe > 0:
                    info += f" | pal_europe=+{round(surcharge_europe,2)}€ ({nb_europe}x)"

                if info_multi:
                    info = info_multi + " | " + info

    results.append((
        "DACHSER",
        base,
        appliquer_taxe_et_rfa(base, "DACHSER", taxes, rfa),
        info
    ))

    # ============================================================
    # KUEHNE (zone difficile via CP + surcharges YAML + zones type)
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
            is_zone_difficile = (code_postal in kuehne_zone)

            dfk = df_kuehne.copy()
            dfk["departement"] = dfk["departement"].astype(str).str.zfill(2)
            dfk = dfk[dfk["departement"] == str(departement).zfill(2)]

            if dfk.empty:
                base = np.nan
                info = "KUEHNE ignoré : département absent"
            else:
                # Choisir ligne difficile / non difficile
                if "difficulte" in dfk.columns:
                    diff = dfk["difficulte"].astype(str).str.strip()
                    has_diff = diff.ne("") & diff.ne("nan")

                    dfk2 = dfk[has_diff] if is_zone_difficile else dfk[~has_diff]
                    if dfk2.empty:
                        dfk2 = dfk
                    row = dfk2.iloc[0]
                else:
                    row = dfk.iloc[0]

                # Prix base
                if cfg_kuehne.get("split_100kg", True) and poids_total > 100:
                    base = trouver_prix_100kg(row, poids_total, cfg_kuehne.get("rounding_10kg", True))
                else:
                    base = trouver_prix_forfait(row, poids_total)

                # --- type de zone (URBAIN / SAISONNIER)
                zone_type = None
                is_urbain = False
                is_saisonnier_zone = False

                # (si tu n’as pas encore branché l’onglet, ces variables resteront False)
                if "kuehne_cp_to_type" in locals() and "kuehne_ranges" in locals() and "kuehne_dept_prefix_type" in locals():
                    zone_type = kuehne_get_type(
                        code_postal, departement,
                        kuehne_cp_to_type, kuehne_ranges, kuehne_dept_prefix_type
                    )
                    is_urbain = (zone_type == "URBAIN")
                    is_saisonnier_zone = (zone_type == "SAISONNIER")

                # Surcharges YAML
                added = 0.0
                details = []

                fixed_fee = float(cfg_kuehne.get("fixed_fee_eur", 0) or 0)
                if fixed_fee > 0:
                    added += fixed_fee
                    details.append(f"forfait={fixed_fee}€")

                europe_fee = float(cfg_kuehne.get("europe_pallet_fee_eur_per_pallet", 0) or 0)
                nb_europe = count_europe_palettes(palettes)
                if europe_fee > 0 and nb_europe > 0:
                    fee = europe_fee * float(nb_europe)
                    added += fee
                    details.append(f"pal_europe=+{round(fee,2)}€")


                # ✅ CORSE : basé sur le code postal 20xxx (pas 2A/2B)
                corsica_fee = float(cfg_kuehne.get("corsica_dept20_fee_eur", 0) or 0)
                if str(code_postal).startswith("20") and corsica_fee > 0:
                    added += corsica_fee
                    details.append(f"corse=+{corsica_fee}€")

                urb_cfg = cfg_kuehne.get("urbain", {})
                if urb_cfg.get("enabled", False) and is_urbain:
                    urb_fee = float(urb_cfg.get("fee_eur", 0) or 0)
                    if urb_fee > 0:
                        added += urb_fee
                        details.append(f"urbain=+{urb_fee}€")

                saison_cfg = cfg_kuehne.get("saisonnier", {})
                if saison_cfg.get("enabled", False) and is_saisonnier_zone:
                    p = saison_cfg.get("period", {})
                    start = p.get("start", "05-01")
                    end = p.get("end", "08-31")

                    if is_in_period_mmdd(start, end):
                        percent = float(saison_cfg.get("percent_of_freight", 0) or 0)
                        if percent > 0 and not pd.isna(base):
                            fee = float(base) * (percent / 100.0)
                            added += fee
                            details.append(f"saisonnier=+{round(percent,2)}%")
                    else:
                        details.append("saisonnier=hors période")

                if not pd.isna(base):
                    base = float(base) + float(added)

                info = (
                    f"Poids total {poids_total} kg"
                    f" | zone difficile={is_zone_difficile}"
                    f" | zone_type={zone_type}"
                )
                if details:
                    info += " | " + " + ".join(details)

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
            # Règles XPO existantes (palette parfaite, formats autorisés, etc.)
            base, info = prix_xpo(df_xpo, departement, palettes, palette_parfaite, cfg_xpo)

            fixed_fee = cfg_xpo.get("fixed_fee_eur", 0) or 0

            # CP flags
            is_acces_difficile = code_postal in xpo_acces_difficile
            is_grande_ville = code_postal in xpo_grande_ville

            surcharge_acces = 0.0
            surcharge_gv = 8.0 if is_grande_ville else 0.0

            # Accès difficile : 15€/100kg (poids taxé) plafonné à 150€
            if is_acces_difficile:
                pt_total = poids_taxe_total_xpo(palettes)

                # Si format palette non supporté => on bloque XPO (et on ne calcule pas)
                if pt_total is None:
                    base = np.nan
                    info = "XPO ignoré : format palette non supporté pour accès difficile (attendu 80x120, 100x120 ou 120x120)"
                else:
                    surcharge_acces = min(150.0, 15.0 * (pt_total / 100.0))

            # Palette Europe : frais par palette Europe (paramétrable)
            europe_fee_per_pallet = float(cfg_xpo.get("europe_pallet_fee_eur_per_pallet", 0) or 0)
            nb_europe = count_europe_palettes(palettes)

            surcharge_europe = 0.0
            if europe_fee_per_pallet > 0 and nb_europe > 0:
                surcharge_europe = europe_fee_per_pallet * float(nb_europe)



            # Ajout des frais si base valide
            if not pd.isna(base):
                base = base + fixed_fee + surcharge_acces + surcharge_gv + surcharge_europe

                info = (
                    f"{info}"
                    f" + forfait {fixed_fee}€"
                    f" | accès difficile={is_acces_difficile}"
                    f" | palettes_europe={nb_europe} (+{round(surcharge_europe,2)}€)"
                )


                if is_acces_difficile:
                    info += f" (poids taxé={pt_total} kg, +{round(surcharge_acces,2)}€)"
                else:
                    info += " (+0€)"

                info += f" | grande ville={is_grande_ville} (+{round(surcharge_gv,2)}€)"

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

