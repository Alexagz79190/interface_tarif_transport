import os
import requests

def download_file(url, dest_path, headers=None):
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    with open(dest_path, "wb") as f:
        f.write(r.content)

def get_tarif_files_from_sharepoint(secrets):
    """
    Télécharge les fichiers tarifs depuis SharePoint dans /tmp
    secrets attendus:
      secrets["sharepoint"]["files"]["GEODIS"] = "https://..."
      secrets["sharepoint"]["files"]["XPO"] = "https://..."
      secrets["sharepoint"]["files"]["KUEHNE"] = "https://..."
      secrets["sharepoint"]["files"]["DACHSER"] = "https://..."
      secrets["sharepoint"]["files"]["TAXE_GO"] = "https://..."
    Optionnel:
      secrets["sharepoint"]["auth_header"] = "Bearer ...."
    """
    tmp_dir = "/tmp/tarifs"
    os.makedirs(tmp_dir, exist_ok=True)

    files = secrets["sharepoint"]["files"]

    headers = None
    if "auth_header" in secrets["sharepoint"]:
        headers = {"Authorization": secrets["sharepoint"]["auth_header"]}

    local_paths = {}
    for key, url in files.items():
        dest = os.path.join(tmp_dir, f"{key}")
        # ajoute extension si manquante
        if "GEODIS" in key and not dest.lower().endswith(".xls"):
            dest += ".xls"
        if "XPO" in key and not dest.lower().endswith(".xls"):
            dest += ".xls"
        if "KUEHNE" in key and not dest.lower().endswith(".csv"):
            dest += ".csv"
        if "DACHSER" in key and not dest.lower().endswith(".xlsx"):
            dest += ".xlsx"
        if "TAXE" in key and not dest.lower().endswith(".csv"):
            dest += ".csv"

        download_file(url, dest, headers=headers)
        local_paths[key] = dest

    return local_paths
