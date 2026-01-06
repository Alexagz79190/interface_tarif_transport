import yaml
import os

def load_constraints(path="constraints.yaml"):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Fichier {path} introuvable (constraints).")

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
