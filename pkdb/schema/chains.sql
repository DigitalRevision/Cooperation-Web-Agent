-- sm01_chains — производственные цепочки пользователей: этапы, выбранные поставщики, связи, история замен.

CREATE TABLE chain (
  id         text PRIMARY KEY,
  owner_id   text NOT NULL,                  -- пользователь sm01_accounts
  title      text NOT NULL,
  buyer_city text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  extra      jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX chain_owner ON chain (owner_id, updated_at DESC);

CREATE TABLE chain_node (
  chain_id    text NOT NULL REFERENCES chain ON DELETE CASCADE,
  id          text NOT NULL,
  pos         int  NOT NULL,
  step        text NOT NULL,
  requirement text,
  company_id  text,                          -- поставщик: карточка sm01_catalog
  product_id  text,
  status      text NOT NULL DEFAULT 'EMPTY' CHECK (status IN ('EMPTY','SELECTED','DECLINED','CONFIRMED')),
  extra       jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (chain_id, id)
);

-- Замены поставщика на этапе
CREATE TABLE chain_node_history (
  chain_id     text NOT NULL,
  node_id      text NOT NULL,
  pos          int  NOT NULL,
  from_company text,
  to_company   text,
  reason       text,
  at           timestamptz,
  PRIMARY KEY (chain_id, node_id, pos),
  FOREIGN KEY (chain_id, node_id) REFERENCES chain_node ON DELETE CASCADE
);

-- Связь между соседними этапами: объём, цена и сроки поставки
CREATE TABLE chain_edge (
  chain_id             text NOT NULL REFERENCES chain ON DELETE CASCADE,
  pos                  int  NOT NULL,
  from_node            text NOT NULL,
  to_node              text NOT NULL,
  relation             text NOT NULL DEFAULT 'INFERRED_RELATION'
                       CHECK (relation IN ('CONFIRMED_RELATION','POTENTIAL_RELATION','INFERRED_RELATION')),
  qty                  text,
  unit                 text,
  price                text,
  min_batch            text,
  lead_time_production text,
  lead_time_delivery   text,
  extra                jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (chain_id, pos)
);
