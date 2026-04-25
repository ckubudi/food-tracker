"""
Baixa a Tabela TACO (UNICAMP, 4a ed.) do mirror em github.com/machine-learning-mocha/taco
e normaliza em data/taco.json com schema limpo.

Uso: python scripts/baixar_taco.py
"""
import csv
import io
import json
import re
import sys
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "taco.json"
SOURCE = "https://raw.githubusercontent.com/machine-learning-mocha/taco/main/tabelas/alimentos.csv"


def parse_num(s):
    """Converte string BR (vírgula) em float. NA/Tr/vazio viram None ou 0."""
    if s is None:
        return None
    s = s.strip()
    if s in ("", "NA", "-"):
        return None
    if s == "Tr":  # traço — quantidade desprezível
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def slug(s):
    """Normaliza pra busca: sem acento, lowercase, espaço simples."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s,]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def main():
    print(f"Baixando TACO de {SOURCE}")
    r = requests.get(SOURCE, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"

    reader = csv.DictReader(io.StringIO(r.text), delimiter=";")
    alimentos = []
    for row in reader:
        nome = row["Descrição dos alimentos"].strip()
        alimentos.append({
            "id": int(row["Número do Alimento"]),
            "nome": nome,
            "nome_norm": slug(nome),
            "categoria": row["Categoria do alimento"].strip(),
            "kcal_100g": parse_num(row["Energia (kcal)"]),
            "proteina_g": parse_num(row["Proteína (g)"]),
            "carbo_g": parse_num(row["Carboidrato (g)"]),
            "gordura_g": parse_num(row["Lipídeos (g)"]),
            "fibra_g": parse_num(row["Fibra Alimentar (g)"]),
            "sodio_mg": parse_num(row["Sódio (mg)"]),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"fonte": "TACO 4a ed. / UNICAMP (via machine-learning-mocha/taco)",
                    "url": SOURCE,
                    "alimentos": alimentos},
                   ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"OK: {len(alimentos)} alimentos salvos em {OUT}")


if __name__ == "__main__":
    sys.exit(main())
