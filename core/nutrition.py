"""
Lookup nutricional local (TACO + Open Food Facts).

Na arquitetura MCP, o Claude do app faz parsing e pesquisa de restaurantes/marcas
obscuras via web_search nativo. O backend cobre duas fontes "automáticas":

  - TACO (597 alimentos, UNICAMP) — para genéricos (arroz, ovo, banana...)
  - Open Food Facts — para produtos industrializados com código de barras/marca

Lookups são cacheados em SQLite por (tipo, nome_normalizado).
"""
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

import requests

from core import db

ROOT = Path(__file__).resolve().parent.parent
TACO_PATH = ROOT / "data" / "taco.json"

OFF_API = "https://world.openfoodfacts.org/cgi/search.pl"


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _escalar_100g(macros_100g: dict, qtd_g: float) -> dict:
    f = qtd_g / 100.0
    out = {}
    for k in ("kcal", "proteina_g", "carbo_g", "gordura_g", "fibra_g", "sodio_mg"):
        v = macros_100g.get(k)
        out[k] = round(v * f, 1) if isinstance(v, (int, float)) else None
    return out


# ---------- TACO ----------

_TACO_CACHE = None

def _taco():
    global _TACO_CACHE
    if _TACO_CACHE is None:
        _TACO_CACHE = _load_json(TACO_PATH, {"alimentos": []})["alimentos"]
    return _TACO_CACHE


def buscar_taco(nome: str) -> Optional[dict]:
    """Fuzzy match por similaridade + palavras em comum."""
    alvo = _slug(nome)
    alimentos = _taco()
    palavras_alvo = [p for p in alvo.split() if len(p) > 2]

    melhor = None
    melhor_score = -1.0
    for a in alimentos:
        score = SequenceMatcher(None, alvo, a["nome_norm"]).ratio()
        if palavras_alvo:
            match = sum(1 for p in palavras_alvo if p in a["nome_norm"])
            falta = len(palavras_alvo) - match
            score += 0.4 * (match / len(palavras_alvo))
            score -= 0.15 * falta
        if score > melhor_score:
            melhor_score = score
            melhor = a

    if melhor and melhor_score >= 0.55:
        return {
            "fonte": "TACO",
            "nome_encontrado": melhor["nome"],
            "score": round(melhor_score, 2),
            "macros_100g": {
                "kcal": melhor["kcal_100g"],
                "proteina_g": melhor["proteina_g"],
                "carbo_g": melhor["carbo_g"],
                "gordura_g": melhor["gordura_g"],
                "fibra_g": melhor["fibra_g"],
                "sodio_mg": melhor["sodio_mg"],
            }
        }
    return None


# ---------- Open Food Facts ----------

def buscar_off(nome: str, marca: Optional[str] = None) -> Optional[dict]:
    termo = f"{marca} {nome}" if marca else nome
    params = {
        "search_terms": termo,
        "search_simple": 1,
        "action": "process",
        "json": 1,
        "page_size": 3,
        "fields": "product_name,brands,nutriments,countries_tags,quantity",
    }
    try:
        r = requests.get(OFF_API, params=params, timeout=15,
                         headers={"User-Agent": "food-tracker/1.0"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"OFF erro: {e}")
        return None

    products = data.get("products", [])
    products.sort(key=lambda p: 0 if "en:brazil" in p.get("countries_tags", []) else 1)

    for p in products:
        nut = p.get("nutriments", {})
        kcal = nut.get("energy-kcal_100g")
        if kcal is None:
            continue
        return {
            "fonte": "OpenFoodFacts",
            "nome_encontrado": f"{p.get('product_name', '')} ({p.get('brands', '')})".strip(),
            "macros_100g": {
                "kcal": kcal,
                "proteina_g": nut.get("proteins_100g"),
                "carbo_g": nut.get("carbohydrates_100g"),
                "gordura_g": nut.get("fat_100g"),
                "fibra_g": nut.get("fiber_100g"),
                "sodio_mg": (nut.get("sodium_100g") or 0) * 1000 if nut.get("sodium_100g") else None,
            }
        }
    return None


# ---------- API pública ----------

def resolver_item(item: dict) -> dict:
    """Resolve macros de um item vindo do Claude app.

    Formato esperado do item:
      nome: str
      tipo: "generico" | "marca" | "restaurante" | "caseiro"  (opcional)
      qtd_g: float | None
      qtd_porcoes: float | None
      marca: str | None
      restaurante: str | None
      observacao: str | None
      macros: {kcal, proteina_g, carbo_g, gordura_g, fibra_g?, sodio_mg?}  -- opcional
      base: "por_100g" | "por_porcao"  -- opcional, default por_porcao se macros vier
      fonte_url: str | None  -- opcional

    Fluxo:
      1. Se item["macros"] veio preenchido (Claude pesquisou), usa direto.
      2. Senão, tenta cache por (tipo, nome).
      3. Senão, tenta TACO (se tipo=generico) ou OFF (se tipo=marca).
      4. Se ainda não achou, retorna erro — Claude deve retry com macros preenchidos.
    """
    nome = item["nome"]
    tipo = item.get("tipo", "generico")

    if item.get("macros"):
        base = item.get("base", "por_porcao")
        qtd_g = item.get("qtd_g")
        qtd_porcoes = item.get("qtd_porcoes") or 1

        if base == "por_100g" and qtd_g:
            macros = _escalar_100g(item["macros"], qtd_g)
        elif base == "por_porcao":
            macros = {k: (v * qtd_porcoes if isinstance(v, (int, float)) else None)
                      for k, v in item["macros"].items()}
        else:
            macros = dict(item["macros"])

        return {
            "item": item,
            "macros": macros,
            "fonte": item.get("fonte") or "Claude",
            "nome_encontrado": nome,
            "fonte_url": item.get("fonte_url"),
            "confianca": item.get("confianca", "alta"),
        }

    resultado_lookup = db.cache_get(tipo, nome)
    if resultado_lookup is None:
        if tipo == "generico":
            resultado_lookup = buscar_taco(nome)
        elif tipo == "marca":
            resultado_lookup = buscar_off(nome, item.get("marca"))
        if resultado_lookup is not None:
            db.cache_set(tipo, nome, resultado_lookup)

    if resultado_lookup is None:
        return {
            "erro": (f"Não achei '{nome}' (tipo={tipo}) em TACO/OFF. "
                     f"Pesquise via web_search e chame registrar_refeicao de novo "
                     f"preenchendo o campo 'macros' do item."),
            "item": item,
        }

    qtd_g = item.get("qtd_g")
    qtd_porcoes = item.get("qtd_porcoes") or 1

    if "macros_100g" in resultado_lookup and qtd_g:
        macros = _escalar_100g(resultado_lookup["macros_100g"], qtd_g)
    elif "macros_100g" in resultado_lookup:
        macros = resultado_lookup["macros_100g"]
    else:
        macros = resultado_lookup.get("macros", {})

    return {
        "item": item,
        "macros": macros,
        "fonte": resultado_lookup.get("fonte"),
        "nome_encontrado": resultado_lookup.get("nome_encontrado"),
        "confianca": resultado_lookup.get("confianca", "alta"),
        "fonte_url": resultado_lookup.get("fonte_url"),
    }


def resolver_refeicao(itens: list[dict]) -> dict:
    resultados = [resolver_item(it) for it in itens]
    total = {"kcal": 0, "proteina_g": 0, "carbo_g": 0, "gordura_g": 0,
             "fibra_g": 0, "sodio_mg": 0}
    for r in resultados:
        if "erro" in r:
            continue
        for k, v in (r.get("macros") or {}).items():
            if isinstance(v, (int, float)):
                total[k] = round(total.get(k, 0) + v, 1)
    return {"itens": resultados, "total": total}
