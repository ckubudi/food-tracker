-- Food Tracker - schema Postgres (Supabase)
-- Rode esse arquivo no Supabase Studio: SQL Editor → New Query → cole tudo → Run.

create table if not exists refeicoes (
    id              bigserial primary key,
    timestamp       timestamptz not null default now(),
    dia             date not null,
    descricao       text not null,
    total_kcal          double precision,
    total_proteina_g    double precision,
    total_carbo_g       double precision,
    total_gordura_g     double precision,
    total_fibra_g       double precision,
    total_sodio_mg      double precision
);
create index if not exists idx_refeicoes_dia on refeicoes(dia);
create index if not exists idx_refeicoes_ts  on refeicoes(timestamp);

create table if not exists itens (
    id              bigserial primary key,
    refeicao_id     bigint not null references refeicoes(id) on delete cascade,
    nome            text,
    tipo            text,
    marca           text,
    restaurante     text,
    qtd_g           double precision,
    qtd_porcoes     double precision,
    observacao      text,
    fonte           text,
    nome_encontrado text,
    fonte_url       text,
    confianca       text,
    kcal            double precision,
    proteina_g      double precision,
    carbo_g         double precision,
    gordura_g       double precision,
    fibra_g         double precision,
    sodio_mg        double precision,
    erro            text
);
create index if not exists idx_itens_refeicao on itens(refeicao_id);

create table if not exists cache_nutricao (
    chave       text primary key,
    dados_json  jsonb not null,
    criado_em   timestamptz not null default now()
);

-- RLS: tabelas privadas (apenas service_role acessa via Vercel).
-- Se quiser dashboard público, criar policy SELECT pra anon depois.
alter table refeicoes      enable row level security;
alter table itens          enable row level security;
alter table cache_nutricao enable row level security;
