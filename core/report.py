"""
Gera dashboard HTML estático a partir do SQLite (data/food.db).

Segue paleta do CLAUDE.md: #1a237e/#283593/#3949ab, metric-boxes, Plotly CDN.
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from core import db
from core.db import _now_local, hoje_local

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
OUTPUT_PATH = ROOT / "pages" / "index.html"


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _barra_progresso(valor: float, meta: float, cor: str) -> str:
    pct = min(valor / meta * 100, 130) if meta else 0
    fill_cor = cor if pct <= 110 else "#c62828"
    return (f'<div class="progress-wrap"><div class="progress-fill" '
            f'style="width:{pct:.0f}%; background:{fill_cor};"></div>'
            f'<span class="progress-label">{valor:.0f} / {meta:.0f} '
            f'({pct:.0f}%)</span></div>')


def _html_metric(label: str, valor: float, meta: float, unidade: str, cor: str) -> str:
    pct = (valor / meta * 100) if meta else 0
    classe = "green" if pct <= 105 else "red" if pct > 115 else "neutral"
    return f"""<div class="metric-box {classe}">
<div class="value">{valor:.0f}<span class="unit">{unidade}</span></div>
<div class="label">{label}</div>
{_barra_progresso(valor, meta, cor)}
</div>"""


def _html_tabela_refeicoes(refs: list) -> str:
    if not refs:
        return '<p style="color:#888">Nenhuma refeição registrada hoje.</p>'

    html = ('<div class="table-wrap"><table class="stats-table"><thead><tr>'
            '<th>Hora</th><th>Descrição</th><th>kcal</th><th>P</th>'
            '<th>C</th><th>G</th></tr></thead><tbody>')
    for r in refs:
        hora = r["timestamp"][11:16]
        itens_txt = ", ".join(
            (f'{i["nome"] or "?"}' +
             (f' ({i["qtd_g"]:.0f}g)' if i.get("qtd_g") else ""))
            for i in r.get("itens", [])
        )
        html += (f'<tr><td>{hora}</td>'
                 f'<td>{r["descricao"]}'
                 f'<div style="font-size:.8em; color:#888; margin-top:2px">{itens_txt}</div></td>'
                 f'<td>{(r["total_kcal"] or 0):.0f}</td>'
                 f'<td>{(r["total_proteina_g"] or 0):.0f}</td>'
                 f'<td>{(r["total_carbo_g"] or 0):.0f}</td>'
                 f'<td>{(r["total_gordura_g"] or 0):.0f}</td></tr>')
    html += '</tbody></table></div>'
    return html


def _plotly_30d(por_dia: dict, metas: dict) -> str:
    hoje = _now_local().date()
    dias = [(hoje - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    kcal = [por_dia.get(d, {}).get("kcal", 0) for d in dias]
    prot = [por_dia.get(d, {}).get("proteina_g", 0) for d in dias]
    carb = [por_dia.get(d, {}).get("carbo_g", 0) for d in dias]
    gord = [por_dia.get(d, {}).get("gordura_g", 0) for d in dias]

    dias_js = json.dumps(dias)
    return f"""
<div id="chart-kcal" style="height:320px"></div>
<div id="chart-macros" style="height:320px; margin-top:20px"></div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>
var dias = {dias_js};
Plotly.newPlot('chart-kcal', [
  {{x: dias, y: {json.dumps(kcal)}, type:'bar', name:'kcal',
    marker:{{color:'#3949ab'}}}},
  {{x: dias, y: Array(dias.length).fill({metas['kcal']}), name:'meta',
    type:'scatter', mode:'lines', line:{{color:'#c62828', dash:'dash', width:2}}}}
], {{
  title: {{text:'Calorias — últimos 30 dias', font:{{size:14, color:'#283593'}}}},
  plot_bgcolor:'#fafafa', paper_bgcolor:'#fafafa',
  font:{{family:'Segoe UI, Tahoma, sans-serif'}},
  margin:{{t:40, b:40, l:50, r:20}}, hovermode:'x unified'
}}, {{responsive:true}});

Plotly.newPlot('chart-macros', [
  {{x: dias, y: {json.dumps(prot)}, name:'Proteína', type:'scatter',
    mode:'lines+markers', line:{{color:'#2e7d32', width:2}}}},
  {{x: dias, y: {json.dumps(carb)}, name:'Carboidrato', type:'scatter',
    mode:'lines+markers', line:{{color:'#1565c0', width:2}}}},
  {{x: dias, y: {json.dumps(gord)}, name:'Gordura', type:'scatter',
    mode:'lines+markers', line:{{color:'#f57f17', width:2}}}}
], {{
  title: {{text:'Macros (g) — últimos 30 dias', font:{{size:14, color:'#283593'}}}},
  plot_bgcolor:'#fafafa', paper_bgcolor:'#fafafa',
  font:{{family:'Segoe UI, Tahoma, sans-serif'}},
  margin:{{t:40, b:40, l:50, r:20}}, hovermode:'x unified',
  legend:{{orientation:'h', y:1.1}}
}}, {{responsive:true}});
</script>"""


def _adherence_7d(por_dia: dict, metas: dict) -> str:
    hoje = _now_local().date()
    dias = [(hoje - timedelta(days=i)).isoformat() for i in range(7)]
    cont = {"kcal": 0, "proteina_g": 0, "carbo_g": 0, "gordura_g": 0}
    dias_com_registro = 0
    for d in dias:
        if d in por_dia and por_dia[d]["kcal"] > 500:
            dias_com_registro += 1
            for k in cont:
                cont[k] += por_dia[d][k]

    if dias_com_registro == 0:
        return "<p>Sem registros na última semana.</p>"

    html = ('<table class="stats-table"><thead><tr><th>Macro</th><th>Média 7d</th>'
            '<th>Meta</th><th>Aderência</th></tr></thead><tbody>')
    for k, meta_key, label, unit in [
        ("kcal", "kcal", "Calorias", "kcal"),
        ("proteina_g", "proteina_g", "Proteína", "g"),
        ("carbo_g", "carbo_g", "Carboidrato", "g"),
        ("gordura_g", "gordura_g", "Gordura", "g"),
    ]:
        media = cont[k] / dias_com_registro
        meta = metas[meta_key]
        pct = media / meta * 100
        cor = "#2e7d32" if 90 <= pct <= 110 else "#f57f17" if 75 <= pct <= 125 else "#c62828"
        html += (f'<tr><td>{label}</td><td>{media:.0f} {unit}</td><td>{meta} {unit}</td>'
                 f'<td style="color:{cor}; font-weight:bold">{pct:.0f}%</td></tr>')
    html += '</tbody></table>'
    html += (f'<p style="color:#888; font-size:.9em">Média sobre '
             f'{dias_com_registro} dia(s) com registros.</p>')
    return html


CSS = """
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Tahoma, sans-serif;
       max-width: 1100px; margin: 20px auto; padding: 0 16px;
       background: #fafafa; color: #333; line-height: 1.5; }
h1 { color: #1a237e; border-bottom: 3px solid #1a237e; padding-bottom: 10px;
     font-size: 1.6em; margin: 0 0 6px; }
h2 { color: #283593; margin-top: 30px; border-bottom: 1px solid #ccc;
     padding-bottom: 6px; font-size: 1.25em; }
h3 { color: #3949ab; margin-top: 22px; font-size: 1.1em; }
.metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
               gap: 10px; margin: 16px 0; }
.metric-box { background: white; border: 1px solid #ddd; border-radius: 10px;
              padding: 14px 12px; text-align: center; }
.metric-box .value { font-size: 1.8em; font-weight: bold; color: #1a237e; line-height: 1.1; }
.metric-box .unit { font-size: .5em; color: #888; margin-left: 3px; }
.metric-box .label { font-size: .85em; color: #555; margin-bottom: 8px; }
.metric-box.green .value { color: #2e7d32; }
.metric-box.red .value { color: #c62828; }
.metric-box.neutral .value { color: #f57f17; }
.progress-wrap { position: relative; height: 16px; background: #e0e0e0; border-radius: 8px;
                 overflow: hidden; margin-top: 8px; }
.progress-fill { height: 100%; transition: width .3s; }
.progress-label { position: absolute; top: 0; left: 0; right: 0; text-align: center;
                  font-size: .72em; line-height: 16px; color: #222; font-weight: 600; }
.table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch;
              border-radius: 6px; margin: 12px 0;
              background: white; border: 1px solid #eee; }
.stats-table { border-collapse: collapse; width: 100%; min-width: 520px; }
.stats-table th { background: #1a237e; color: white; padding: 9px 12px;
                  text-align: left; font-size: .9em; white-space: nowrap; }
.stats-table td { padding: 8px 12px; border-bottom: 1px solid #eee; vertical-align: top; }
.stats-table tbody tr:nth-child(even) { background: #f5f5f5; }
.conclusion { background: #e8eaf6; border-left: 4px solid #1a237e;
              padding: 12px 16px; margin: 16px 0; border-radius: 4px; font-size: .95em; }
.nota { background: #fff3e0; border-left: 4px solid #ff9800;
        padding: 10px 14px; margin: 12px 0; font-size: .9em; }
.footer { margin-top: 32px; color: #888; font-size: 11px;
          border-top: 1px solid #ccc; padding-top: 10px; }
.js-plotly-plot { max-width: 100%; }

@media (max-width: 600px) {
    body { margin: 10px auto; padding: 0 10px; line-height: 1.4; }
    h1 { font-size: 1.3em; padding-bottom: 6px; }
    h2 { font-size: 1.1em; margin-top: 22px; }
    h3 { font-size: 1em; margin-top: 16px; }
    .metric-grid { grid-template-columns: repeat(2, 1fr); gap: 8px; }
    .metric-box { padding: 10px 8px; }
    .metric-box .value { font-size: 1.5em; }
    .metric-box .label { font-size: .78em; }
    .stats-table th, .stats-table td { padding: 7px 9px; font-size: .85em; }
    .conclusion, .nota { font-size: .88em; padding: 10px 12px; }
}
"""


def gerar_html(config_path: Path = CONFIG_PATH) -> str:
    """Monta o HTML do dashboard e devolve como string."""
    cfg = _load(config_path)
    metas = cfg["metas_diarias"]

    hoje = hoje_local()
    por_dia = db.serie_historica(30)
    dia_atual = por_dia.get(hoje, {"kcal": 0, "proteina_g": 0, "carbo_g": 0,
                                   "gordura_g": 0, "fibra_g": 0, "sodio_mg": 0})
    refs_hoje = db.refeicoes_do_dia(hoje)
    agora = _now_local().strftime("%d/%m/%Y %H:%M")

    return f"""<!doctype html>
<html lang="pt-br"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Food Tracker — {hoje}</title>
<style>{CSS}</style></head>
<body>
<h1>🍽️ Food Tracker</h1>
<p><strong>{hoje}</strong> · atualizado {agora}</p>

<h2>Hoje</h2>
<div class="metric-grid">
{_html_metric("Calorias", dia_atual["kcal"], metas["kcal"], " kcal", "#3949ab")}
{_html_metric("Proteína", dia_atual["proteina_g"], metas["proteina_g"], "g", "#2e7d32")}
{_html_metric("Carboidrato", dia_atual["carbo_g"], metas["carbo_g"], "g", "#1565c0")}
{_html_metric("Gordura", dia_atual["gordura_g"], metas["gordura_g"], "g", "#f57f17")}
{_html_metric("Fibra", dia_atual["fibra_g"], metas["fibra_g"], "g", "#6a1b9a")}
</div>

<h3>Refeições do dia</h3>
{_html_tabela_refeicoes(refs_hoje)}

<h2>Últimos 30 dias</h2>
{_plotly_30d(por_dia, metas)}

<h2>Aderência (7 dias)</h2>
{_adherence_7d(por_dia, metas)}

<div class="conclusion">
<strong>Registrar refeição:</strong> converse com seu Claude app — ele parseia a
descrição, busca as tabelas e atualiza este dashboard.
</div>

<div class="footer">Food Tracker · fontes: TACO 4ª ed. (UNICAMP) · Open Food Facts · restaurantes via Claude web_search</div>
</body></html>"""


def gerar(output_path: Path = OUTPUT_PATH, config_path: Path = CONFIG_PATH) -> Path:
    html = gerar_html(config_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


if __name__ == "__main__":
    path = gerar()
    print(f"Dashboard gerado: {path}")
