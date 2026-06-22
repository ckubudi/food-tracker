"""
Configuração runtime — combina env vars (prioridade) com config.json (fallback).

Por que env var: deploys diferentes (Charles vs Rui) usam o MESMO repo no GitHub.
As metas e o nome do usuário variam por deploy → vão como env var no Vercel,
não como arquivo no repo.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"

_DEFAULT_METAS = {
    "kcal": 2200,
    "proteina_g": 150,
    "carbo_g": 220,
    "gordura_g": 70,
    "fibra_g": 25,
}


def _load_config_file() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _metas_estaticas() -> dict:
    """METAS_JSON env var > config.json > default."""
    env = os.environ.get("METAS_JSON")
    if env:
        try:
            return json.loads(env)
        except Exception as e:
            raise SystemExit(f"METAS_JSON inválido: {e}")
    cfg = _load_config_file()
    return cfg.get("metas_diarias", _DEFAULT_METAS)


def get_metas() -> dict:
    """Tabela `metas` no DB > METAS_JSON env var > config.json > default.

    O DB ganha prioridade pra permitir edição via tool MCP (set_metas).
    Campos não definidos no DB caem no fallback estático.
    """
    base = _metas_estaticas()
    try:
        from core import db  # import lazy: db importa settings indiretamente em alguns fluxos
        db_metas = db.get_metas_db()
    except Exception:
        db_metas = None
    if db_metas:
        return {**base, **db_metas}
    return base


def get_user_name() -> str:
    """USER_NAME env var > config.json[user_name] > '' (default)."""
    return os.environ.get("USER_NAME") or _load_config_file().get("user_name", "")
