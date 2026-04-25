# Food Tracker

Sistema pessoal de monitoramento de macros/kcal via Telegram.

## Como funciona

1. Manda mensagem pro bot Telegram: *"comi 2 ovos mexidos e 150g de arroz"*
2. Bot parseia com Claude API, bate contra tabela nutricional (TACO + Open Food Facts)
3. Registra no `data/refeicoes.json` e confirma com macros somados do dia
4. Resumo das 22h via WhatsApp (CallMeBot) + dashboard em github.io/food-tracker/

## Stack

- **Backend:** Vercel Functions (Python) — webhook do Telegram
- **Parser:** Claude Haiku 4.5 (via `anthropic` SDK)
- **Dados nutricionais:** TACO (local, CSV) + Open Food Facts API
- **Storage:** JSON em repo (GitHub)
- **Dashboard:** GitHub Pages com Plotly
- **Alertas:** WhatsApp via CallMeBot (reusa setup do flight-monitor)

## Estrutura

```
food-tracker/
├── config.json              # metas diárias + tokens
├── api/
│   └── telegram.py          # endpoint Vercel p/ webhook Telegram
├── core/
│   ├── parser.py            # texto livre → itens estruturados (Claude)
│   ├── nutrition.py         # lookup TACO + Open Food Facts
│   └── report.py            # gera HTML dashboard
├── data/
│   ├── taco.csv             # tabela TACO baixada
│   ├── refeicoes.json       # histórico de refeições
│   └── cache_nutricao.json  # cache de lookups
├── pages/
│   └── index.html           # dashboard (gerado)
└── scripts/
    ├── baixar_taco.py       # popula taco.csv
    ├── resumo_diario.py     # roda 22h, envia WhatsApp, atualiza pages
    └── deploy.py            # push pro GitHub Pages (do flight-monitor)
```

## Credenciais necessárias

- [ ] Bot Telegram (via @BotFather): token + chat_id
- [ ] `ANTHROPIC_API_KEY` (Claude API)
- [ ] Conta Vercel (grátis) + link com repo GitHub
- [ ] Repo `food-tracker-pages` público (GitHub Pages)
