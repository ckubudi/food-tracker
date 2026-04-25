"""Popula data/food.db com refeições fake (30 dias) pra preview do dashboard."""
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db

random.seed(42)
db.init()

# Limpa refeições/itens existentes (mantém cache_nutricao)
with db.conn() as c:
    c.execute("DELETE FROM itens")
    c.execute("DELETE FROM refeicoes")
    c.execute("DELETE FROM sqlite_sequence WHERE name IN ('refeicoes','itens')")

hoje = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

DESCRICOES = [
    "omelete de 3 ovos com queijo e pão",
    "bowl de frango com arroz e brócolis",
    "sanduíche de peito de peru integral",
    "Yopro 25g + banana",
    "lasanha à bolonhesa porção média",
    "sashimi de salmão 10 peças",
    "açaí M Oakberry com granola e banana",
]

count = 0
for dias_atras in range(30, -1, -1):
    dia = hoje - timedelta(days=dias_atras)
    n = random.choice([3, 3, 4, 4])
    horarios = [(8, 10), (12, 14), (16, 18), (19, 21)][:n]
    for h_min, h_max in horarios:
        ts = dia.replace(hour=random.randint(h_min, h_max),
                          minute=random.randint(0, 59))
        total = {
            "kcal": round(max(random.gauss(550, 120), 100), 1),
            "proteina_g": round(max(random.gauss(38, 10), 5), 1),
            "carbo_g": round(max(random.gauss(55, 15), 5), 1),
            "gordura_g": round(max(random.gauss(18, 6), 3), 1),
            "fibra_g": round(max(random.gauss(5, 2), 0), 1),
            "sodio_mg": round(max(random.gauss(600, 200), 50), 0),
        }
        resultado_fake = {"itens": [], "total": total}
        db.salvar_refeicao(
            random.choice(DESCRICOES), resultado_fake,
            timestamp=ts.isoformat(timespec="seconds")
        )
        count += 1

print(f"OK: {count} refeições fake inseridas no SQLite")
