"""
Food Tracker — MCP server (Streamable HTTP).

Expõe tools pro Claude app:
  - registrar_refeicao
  - resumo_dia
  - listar_refeicoes
  - desfazer_ultima
  - serie_historica
  - get_metas
  - buscar_alimento_taco
  - buscar_alimento_off

Auth: URL contém segredo no path (MCP_AUTH_SECRET). Configurar via .env.
Rodar local:
  uvicorn server.mcp_server:app --host 0.0.0.0 --port 8000
Expor via ngrok pro Claude.ai cadastrar connector custom.
"""
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.routing import Route

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db, nutrition
from core.db import TZ_LOCAL, _now_local
from core.report import gerar_html
from core.settings import get_metas, get_user_name

ENV_PATH = ROOT / ".env"

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("food-mcp")


def _load_env():
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())




_load_env()
db.init()


# ---------- FastMCP ----------

instrucoes = """\
Você é o backend de um tracker nutricional pessoal. O usuário fala em português
brasileiro e descreve refeições em texto livre. Você (Claude) deve:

1. PARSEAR a descrição em itens estruturados. Convenções:
   - 1 ovo = 50g
   - 1 colher sopa de azeite/óleo = 10g
   - 1 fatia de pão de forma = 25g
   - 1 copo de leite (200ml) = 200g
   - 1 banana média = 100g
   - 1 filé de frango médio = 150g
   Decomponha pratos caseiros em ingredientes quando possível.

2. CLASSIFICAR cada item:
   - "generico": alimento básico (arroz, ovo, peito de frango) — backend faz lookup
     automático na TACO (tabela brasileira oficial).
   - "marca": produto industrializado (Yopro, Cheetos, Coca-Cola Zero) — backend
     tenta Open Food Facts. Se falhar, você pesquisa via web_search e passa o
     campo `macros` manualmente.
   - "restaurante": item de rede (Big Mac, Bowl Oakberry) — você SEMPRE pesquisa
     via web_search no site oficial e passa `macros` + `fonte_url`.
   - "caseiro": prato complexo — você estima `macros` com base em receita padrão.

3. CHAMAR `registrar_refeicao` com a descrição original + lista de itens.

Quando você passar `macros` manualmente no item, use o formato por porção total do
item (já escalado pra quantidade consumida), e defina `base="por_porcao"`. Se preferir
passar por 100g, defina `base="por_100g"` junto com `qtd_g`.

Responda ao usuário com os macros totais registrados + acumulado do dia vs metas,
de forma concisa.
"""

_SECRET = os.environ.get("MCP_AUTH_SECRET")
if not _SECRET:
    raise SystemExit(
        "MCP_AUTH_SECRET não definido no .env. Gere com:\n"
        "  python -c \"import secrets; print(secrets.token_urlsafe(32))\""
    )

mcp = FastMCP(
    "food-tracker",
    instructions=instrucoes,
    streamable_http_path=f"/mcp/{_SECRET}",
    stateless_http=True,
    json_response=True,
    # Atrás de proxy (Vercel): Host varia (vercel.app, *.vercel.app, claude.ai).
    # Auth real é pelo segredo no path; DNS rebinding não se aplica aqui.
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


# ---------- tools ----------

@mcp.tool()
def registrar_refeicao(descricao: str, itens: list[dict],
                       dia: Optional[str] = None) -> dict:
    """Registra uma refeição com seus itens e retorna macros + acumulado do dia.

    Args:
        descricao: texto original da refeição ("2 ovos mexidos e 150g de arroz").
        itens: lista de dicts. Campos por item:
            nome (str, obrigatório): nome específico pra lookup.
            tipo (str): "generico" | "marca" | "restaurante" | "caseiro".
            qtd_g (float | null): quantidade em gramas quando aplicável.
            qtd_porcoes (float | null): nº de porções (pra marca/restaurante).
            marca (str | null): marca quando tipo=marca.
            restaurante (str | null): rede quando tipo=restaurante.
            observacao (str | null): preparo, nota relevante.
            macros (dict | null): {kcal, proteina_g, carbo_g, gordura_g,
                fibra_g?, sodio_mg?} -- se você já pesquisou, passe aqui.
            base (str): "por_porcao" (default) ou "por_100g" -- só relevante
                quando macros vem preenchido.
            fonte_url (str | null): URL da fonte (para restaurante/marca).
        dia: opcional, "YYYY-MM-DD". Default = hoje. Use pra logar refeições de
            dias passados (ex: "ontem comi X" → passe a data de ontem). A hora
            usada é a hora atual (mantém ordenação cronológica dentro do dia).

    Retorna:
        {
          "total_refeicao": {kcal, proteina_g, ...},
          "itens_resolvidos": [...],  -- com macros + fonte + nome_encontrado
          "dia": "YYYY-MM-DD",  -- dia em que a refeição foi registrada
          "total_dia": {kcal, ...},  -- totais do dia da refeição
          "metas": {...},
          "percentual_dia": {kcal, proteina_g, ...},  -- % das metas
          "refeicao_id": int,
          "erros": [...],  -- itens que falharam no lookup
        }
    """
    resultado = nutrition.resolver_refeicao(itens)

    timestamp = None
    dia_efetivo = dia or db.hoje_local()
    if dia:
        now = _now_local()
        target = datetime.strptime(dia, "%Y-%m-%d").replace(
            hour=now.hour, minute=now.minute, second=now.second,
            microsecond=0, tzinfo=TZ_LOCAL,
        )
        timestamp = target.isoformat(timespec="seconds")

    refeicao_id = db.salvar_refeicao(descricao, resultado, timestamp=timestamp)

    total_dia = db.total_do_dia(dia_efetivo)
    metas = get_metas()

    pct = {}
    for k, meta in metas.items():
        if meta and isinstance(total_dia.get(k), (int, float)):
            pct[k] = round(total_dia[k] / meta * 100, 1)

    erros = [r for r in resultado["itens"] if "erro" in r]

    return {
        "refeicao_id": refeicao_id,
        "dia": dia_efetivo,
        "total_refeicao": resultado["total"],
        "itens_resolvidos": resultado["itens"],
        "total_dia": total_dia,
        "metas": metas,
        "percentual_dia": pct,
        "erros": erros,
    }


@mcp.tool()
def resumo_dia(dia: Optional[str] = None) -> dict:
    """Retorna totais do dia, metas e refeições já registradas.

    Args:
        dia: "YYYY-MM-DD". Default = hoje.
    """
    dia = dia or db.hoje_local()
    total = db.total_do_dia(dia)
    refs = db.refeicoes_do_dia(dia)
    metas = get_metas()

    pct = {}
    for k, meta in metas.items():
        if meta and isinstance(total.get(k), (int, float)):
            pct[k] = round(total[k] / meta * 100, 1)

    return {
        "dia": dia,
        "total": total,
        "metas": metas,
        "percentual": pct,
        "refeicoes": [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "descricao": r["descricao"],
                "total": {
                    "kcal": r["total_kcal"],
                    "proteina_g": r["total_proteina_g"],
                    "carbo_g": r["total_carbo_g"],
                    "gordura_g": r["total_gordura_g"],
                    "fibra_g": r["total_fibra_g"],
                },
            }
            for r in refs
        ],
    }


@mcp.tool()
def listar_refeicoes(dia: Optional[str] = None) -> list[dict]:
    """Lista refeições de um dia (default hoje) com itens detalhados."""
    dia = dia or db.hoje_local()
    return db.refeicoes_do_dia(dia)


@mcp.tool()
def desfazer_ultima() -> Optional[dict]:
    """Remove a última refeição registrada. Retorna a refeição desfeita ou null."""
    return db.desfazer_ultima()


@mcp.tool()
def serie_historica(n_dias: int = 7) -> dict:
    """Totais por dia nos últimos N dias. Inclui dias com 0 registros."""
    return db.serie_historica(n_dias)


@mcp.tool(name="get_metas")
def _tool_get_metas() -> dict:
    """Retorna metas diárias configuradas."""
    return get_metas()


@mcp.tool()
def buscar_alimento_taco(nome: str) -> Optional[dict]:
    """Fuzzy search na TACO (tabela brasileira de 597 alimentos).
    Retorna {nome_encontrado, macros_100g, score} ou null.
    Útil pra você validar um nome antes de registrar."""
    return nutrition.buscar_taco(nome)


@mcp.tool()
def buscar_alimento_off(nome: str, marca: Optional[str] = None) -> Optional[dict]:
    """Search na Open Food Facts (cobre produtos industrializados BR)."""
    return nutrition.buscar_off(nome, marca)


# ---------- dashboard HTTP ----------

async def _dashboard_handler(request):
    if request.path_params["secret"] != _SECRET:
        return PlainTextResponse("Not Found", status_code=404)
    try:
        return HTMLResponse(gerar_html())
    except Exception as e:
        log.exception("Falha gerando dashboard")
        return PlainTextResponse(f"Erro: {e}", status_code=500)


async def _health(_):
    return PlainTextResponse("ok")


# ASGI app: URL pro Claude custom connector é https://<host>/mcp/<SECRET>
# Dashboard: https://<host>/dashboard/<SECRET>
app = mcp.streamable_http_app()
app.routes.append(Route("/dashboard/{secret}", _dashboard_handler))
app.routes.append(Route("/health", _health))
