"""
Persistência em Postgres (Supabase).

Conexão via DATABASE_URL (pooler do Supabase em modo transaction):
  postgresql://postgres.<ref>:<senha>@aws-0-<region>.pooler.supabase.com:6543/postgres

Para rodar local sem internet: setar SQLITE_FALLBACK=1 → cai num arquivo SQLite
em data/food.db (modo dev only, schema é equivalente mas sem RLS).
"""
import json
import os
import re
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator, Optional
from zoneinfo import ZoneInfo

TZ_LOCAL = ZoneInfo(os.environ.get("TZ_LOCAL", "America/Sao_Paulo"))


def _now_local() -> datetime:
    return datetime.now(TZ_LOCAL)


def hoje_local() -> str:
    return _now_local().date().isoformat()


def _to_local(dt: datetime) -> datetime:
    """Converte datetime tz-aware pro fuso local. Se naïve, assume UTC (vindo do SQLite)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ_LOCAL)

ROOT = Path(__file__).resolve().parent.parent

DATABASE_URL = os.environ.get("DATABASE_URL")
SQLITE_FALLBACK = os.environ.get("SQLITE_FALLBACK") == "1"
SQLITE_PATH = Path(os.environ.get("FOOD_DB_PATH", str(ROOT / "data" / "food.db")))

USE_PG = bool(DATABASE_URL) and not SQLITE_FALLBACK


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _normalize(row) -> dict:
    """Serializa datetime/date pra ISO string em fuso local.
    Postgres devolve nativos com tz; SQLite devolve string já formatada."""
    out = {}
    for k, v in dict(row).items():
        if isinstance(v, datetime):
            out[k] = _to_local(v).isoformat(timespec="seconds")
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


# ---------- conexão ----------

if USE_PG:
    import psycopg
    from psycopg.rows import dict_row

    @contextmanager
    def conn() -> Iterator["psycopg.Connection"]:
        # prepare_threshold=None desabilita prepared statements.
        # Necessário com Supabase pooler em modo transaction: o pooler reusa
        # conexões físicas, então PREPAREd statements de uma sessão "vazam"
        # pra próxima e dão "prepared statement already exists".
        with psycopg.connect(DATABASE_URL, row_factory=dict_row,
                             prepare_threshold=None) as c:
            yield c

    PH = "%s"  # placeholder Postgres
    RETURNING_ID = "RETURNING id"
else:
    @contextmanager
    def conn() -> Iterator[sqlite3.Connection]:
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(SQLITE_PATH)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        try:
            yield c
            c.commit()
        finally:
            c.close()

    PH = "?"
    RETURNING_ID = ""


def init():
    """Cria tabelas (idempotente). No Postgres, prefira rodar db/schema.sql via Studio."""
    if USE_PG:
        return
    schema_sqlite = """
    CREATE TABLE IF NOT EXISTS refeicoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        dia TEXT NOT NULL,
        descricao TEXT NOT NULL,
        total_kcal REAL, total_proteina_g REAL, total_carbo_g REAL,
        total_gordura_g REAL, total_fibra_g REAL, total_sodio_mg REAL
    );
    CREATE INDEX IF NOT EXISTS idx_refeicoes_dia ON refeicoes(dia);
    CREATE INDEX IF NOT EXISTS idx_refeicoes_ts  ON refeicoes(timestamp);
    CREATE TABLE IF NOT EXISTS itens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        refeicao_id INTEGER NOT NULL REFERENCES refeicoes(id) ON DELETE CASCADE,
        nome TEXT, tipo TEXT, marca TEXT, restaurante TEXT,
        qtd_g REAL, qtd_porcoes REAL, observacao TEXT,
        fonte TEXT, nome_encontrado TEXT, fonte_url TEXT, confianca TEXT,
        kcal REAL, proteina_g REAL, carbo_g REAL, gordura_g REAL,
        fibra_g REAL, sodio_mg REAL, erro TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_itens_refeicao ON itens(refeicao_id);
    CREATE TABLE IF NOT EXISTS cache_nutricao (
        chave TEXT PRIMARY KEY, dados_json TEXT NOT NULL, criado_em TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS metas (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        kcal REAL, proteina_g REAL, carbo_g REAL, gordura_g REAL, fibra_g REAL,
        atualizado_em TEXT NOT NULL
    );
    """
    with conn() as c:
        c.executescript(schema_sqlite)


# ---------- refeições ----------

def salvar_refeicao(descricao: str, resultado_nutricao: dict,
                    timestamp: Optional[str] = None) -> int:
    if timestamp:
        ts = timestamp
        dia = ts[:10]
    else:
        now = _now_local()
        ts = now.isoformat(timespec="seconds")
        dia = now.date().isoformat()
    tot = resultado_nutricao["total"]

    with conn() as c:
        cur = c.execute(
            f"""INSERT INTO refeicoes (timestamp, dia, descricao,
                total_kcal, total_proteina_g, total_carbo_g, total_gordura_g,
                total_fibra_g, total_sodio_mg)
                VALUES ({','.join([PH]*9)}) {RETURNING_ID}""",
            (ts, dia, descricao,
             tot.get("kcal"), tot.get("proteina_g"), tot.get("carbo_g"),
             tot.get("gordura_g"), tot.get("fibra_g"), tot.get("sodio_mg"))
        )
        if USE_PG:
            refeicao_id = cur.fetchone()["id"]
        else:
            refeicao_id = cur.lastrowid

        for r in resultado_nutricao["itens"]:
            if "erro" in r:
                c.execute(
                    f"""INSERT INTO itens (refeicao_id, nome, tipo, erro)
                        VALUES ({','.join([PH]*4)})""",
                    (refeicao_id,
                     r.get("item", {}).get("nome"),
                     r.get("item", {}).get("tipo"),
                     r["erro"])
                )
                continue
            it = r["item"]
            m = r.get("macros") or {}
            c.execute(
                f"""INSERT INTO itens (refeicao_id, nome, tipo, marca, restaurante,
                    qtd_g, qtd_porcoes, observacao, fonte, nome_encontrado,
                    fonte_url, confianca, kcal, proteina_g, carbo_g, gordura_g,
                    fibra_g, sodio_mg)
                    VALUES ({','.join([PH]*18)})""",
                (refeicao_id, it.get("nome"), it.get("tipo"), it.get("marca"),
                 it.get("restaurante"), it.get("qtd_g"), it.get("qtd_porcoes"),
                 it.get("observacao"),
                 r.get("fonte"), r.get("nome_encontrado"), r.get("fonte_url"),
                 r.get("confianca"),
                 m.get("kcal"), m.get("proteina_g"), m.get("carbo_g"),
                 m.get("gordura_g"), m.get("fibra_g"), m.get("sodio_mg"))
            )
    return int(refeicao_id)


def refeicoes_do_dia(dia: str) -> "list[dict]":
    with conn() as c:
        refs = [_normalize(r) for r in c.execute(
            f"SELECT * FROM refeicoes WHERE dia={PH} ORDER BY timestamp", (dia,)
        )]
        for r in refs:
            r["itens"] = [_normalize(i) for i in c.execute(
                f"SELECT * FROM itens WHERE refeicao_id={PH}", (r["id"],)
            )]
        return refs


def refeicoes_e_itens_periodo(n_dias: int) -> dict:
    """Retorna {dia_iso: [refeicoes com itens embutidos]} para os últimos N dias.
    Faz apenas 2 queries (refeicoes + itens), agrupa em Python.
    Use quando precisar de muitos dias — evita N+1 queries."""
    cutoff = (date.today() - timedelta(days=n_dias)).isoformat()
    with conn() as c:
        refs = [_normalize(r) for r in c.execute(
            f"SELECT * FROM refeicoes WHERE dia >= {PH} ORDER BY dia, timestamp",
            (cutoff,)
        )]
        if not refs:
            return {}
        ids = [r["id"] for r in refs]
        placeholders = ",".join([PH] * len(ids))
        itens = [_normalize(i) for i in c.execute(
            f"SELECT * FROM itens WHERE refeicao_id IN ({placeholders})", tuple(ids)
        )]

    itens_por_ref = {}
    for it in itens:
        itens_por_ref.setdefault(it["refeicao_id"], []).append(it)

    por_dia = {}
    for r in refs:
        r["itens"] = itens_por_ref.get(r["id"], [])
        por_dia.setdefault(r["dia"], []).append(r)
    return por_dia


def total_do_dia(dia: str) -> dict:
    with conn() as c:
        row = c.execute(
            f"""SELECT COALESCE(SUM(total_kcal),0) AS kcal,
                       COALESCE(SUM(total_proteina_g),0) AS proteina_g,
                       COALESCE(SUM(total_carbo_g),0) AS carbo_g,
                       COALESCE(SUM(total_gordura_g),0) AS gordura_g,
                       COALESCE(SUM(total_fibra_g),0) AS fibra_g,
                       COALESCE(SUM(total_sodio_mg),0) AS sodio_mg
                FROM refeicoes WHERE dia={PH}""", (dia,)
        ).fetchone()
        return dict(row) if row else {}


def serie_historica(n_dias: int = 30) -> dict:
    with conn() as c:
        cutoff = (date.today() - timedelta(days=n_dias)).isoformat()
        rows = [_normalize(r) for r in c.execute(
            f"""SELECT dia,
                       SUM(total_kcal)       AS kcal,
                       SUM(total_proteina_g) AS proteina_g,
                       SUM(total_carbo_g)    AS carbo_g,
                       SUM(total_gordura_g)  AS gordura_g,
                       SUM(total_fibra_g)    AS fibra_g,
                       SUM(total_sodio_mg)   AS sodio_mg
                FROM refeicoes
                WHERE dia >= {PH}
                GROUP BY dia""", (cutoff,)
        ).fetchall()]
        return {r["dia"]: {k: r[k] or 0 for k in
                           ("kcal", "proteina_g", "carbo_g", "gordura_g",
                            "fibra_g", "sodio_mg")}
                for r in rows}


def desfazer_ultima() -> Optional[dict]:
    with conn() as c:
        row = c.execute(
            "SELECT * FROM refeicoes ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        row = _normalize(row)
        c.execute(f"DELETE FROM refeicoes WHERE id={PH}", (row["id"],))
        return row


# ---------- cache nutricional ----------

def cache_get(tipo: str, nome: str) -> Optional[dict]:
    chave = f"{tipo}::{_slug(nome)}"
    with conn() as c:
        row = c.execute(
            f"SELECT dados_json FROM cache_nutricao WHERE chave={PH}", (chave,)
        ).fetchone()
        if not row:
            return None
        dados = row["dados_json"]
        return dados if isinstance(dados, dict) else json.loads(dados)


def cache_set(tipo: str, nome: str, dados: dict):
    chave = f"{tipo}::{_slug(nome)}"
    payload = dados if USE_PG else json.dumps(dados, ensure_ascii=False)
    now = datetime.now().isoformat(timespec="seconds")
    with conn() as c:
        if USE_PG:
            from psycopg.types.json import Jsonb
            c.execute(
                f"""INSERT INTO cache_nutricao (chave, dados_json, criado_em)
                    VALUES ({PH}, {PH}, {PH})
                    ON CONFLICT (chave) DO UPDATE SET dados_json=EXCLUDED.dados_json,
                                                     criado_em=EXCLUDED.criado_em""",
                (chave, Jsonb(dados), now)
            )
        else:
            c.execute(
                """INSERT OR REPLACE INTO cache_nutricao (chave, dados_json, criado_em)
                   VALUES (?, ?, ?)""",
                (chave, payload, now)
            )


_META_KEYS = ("kcal", "proteina_g", "carbo_g", "gordura_g", "fibra_g")


def get_metas_db() -> Optional[dict]:
    """Lê metas da tabela `metas` (id=1). Retorna None se não houver row
    ou se todos os campos forem null."""
    with conn() as c:
        row = c.execute(
            f"SELECT {', '.join(_META_KEYS)} FROM metas WHERE id=1"
        ).fetchone()
        if not row:
            return None
        d = {k: row[k] for k in _META_KEYS}
        if all(v is None for v in d.values()):
            return None
        return {k: v for k, v in d.items() if v is not None}


def set_metas_db(metas: dict) -> dict:
    """Upsert da row de metas (id=1). Faz merge: campos não passados
    (ou com valor None) preservam o valor anterior. Retorna o estado final."""
    atual = get_metas_db() or {}
    novos = {k: v for k, v in metas.items() if k in _META_KEYS and v is not None}
    merged = {**atual, **novos}
    now = datetime.now().isoformat(timespec="seconds")
    vals = tuple(merged.get(k) for k in _META_KEYS)
    with conn() as c:
        if USE_PG:
            c.execute(
                f"""INSERT INTO metas (id, kcal, proteina_g, carbo_g, gordura_g,
                        fibra_g, atualizado_em)
                    VALUES (1, {', '.join([PH]*6)})
                    ON CONFLICT (id) DO UPDATE SET
                        kcal=EXCLUDED.kcal, proteina_g=EXCLUDED.proteina_g,
                        carbo_g=EXCLUDED.carbo_g, gordura_g=EXCLUDED.gordura_g,
                        fibra_g=EXCLUDED.fibra_g, atualizado_em=EXCLUDED.atualizado_em""",
                vals + (now,)
            )
        else:
            c.execute(
                """INSERT OR REPLACE INTO metas (id, kcal, proteina_g, carbo_g,
                       gordura_g, fibra_g, atualizado_em)
                   VALUES (1, ?, ?, ?, ?, ?, ?)""",
                vals + (now,)
            )
    return merged


if __name__ == "__main__":
    init()
    print(f"DB inicializado. Modo: {'Postgres (Supabase)' if USE_PG else 'SQLite local'}")
