-- sm01_market — биржа кооперации: предложения поставщиков, заявки покупателей, отклики на заявки.
-- Автор записи — пользователь из sm01_accounts (author_id), предприятие — карточка sm01_catalog (company_id).
-- Базы разные, поэтому ссылки между ними проверяет API при записи, а не внешний ключ.

-- Предложение о продаже. Цена всегда со всеми атрибутами; price_value NULL — «Цена по запросу»
CREATE TABLE offer (
  id                   text PRIMARY KEY,
  author_id            text NOT NULL,
  company_id           text,
  company_name         text,
  title                text NOT NULL,
  category             text,
  description          text,
  material             text,
  okpd2                text,
  specs                text,
  qty                  numeric,
  unit                 text,
  price_value          numeric CHECK (price_value >= 0),
  price_currency       text,
  price_unit           text,
  price_date           date,
  price_negotiable     boolean,              -- торг возможен; false — цена окончательная; NULL у «Цены по запросу»
  price_source         text CHECK (price_source IN ('SELLER','OPEN_SOURCE')),
  country              text,
  min_batch            text,
  lead_time_production text,
  lead_time_delivery   text,
  city                 text,
  warehouse            text,
  terms                text,
  docs                 text,
  status               text NOT NULL DEFAULT 'NEW',   -- прежняя отметка в записи; решение модератора — в sm01_moderation
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  extra                jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX offer_author ON offer (author_id);
CREATE INDEX offer_company ON offer (company_id);
CREATE INDEX offer_created ON offer (created_at DESC);

-- Заявка на покупку
CREATE TABLE purchase_request (
  id                text PRIMARY KEY,
  author_id         text NOT NULL,
  company_id        text,                   -- предприятие автора
  target_company_id text,                   -- адресная заявка конкретному предприятию
  target_product_id text,
  what              text NOT NULL,
  qty               numeric,
  unit              text,
  period            text,
  material          text,
  okpd2             text,
  specs             text,
  certificates      text,
  deadline          date,
  region_code       text,
  region_name       text,
  city              text,
  max_distance_km   int,
  budget            numeric CHECK (budget >= 0),
  requirements      text,                   -- «Дополнительные требования»
  parsed_query      jsonb,                  -- разбор запроса при создании через API
  status            text NOT NULL DEFAULT 'NEW',
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz NOT NULL DEFAULT now(),
  extra             jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX purchase_request_author ON purchase_request (author_id);
CREATE INDEX purchase_request_target ON purchase_request (target_company_id);
CREATE INDEX purchase_request_created ON purchase_request (created_at DESC);

-- Подобранные поставщики с объяснением совпадения (снимок на момент создания заявки)
CREATE TABLE request_supplier (
  request_id text NOT NULL REFERENCES purchase_request ON DELETE CASCADE,
  company_id text NOT NULL,
  pos        int  NOT NULL,
  match      jsonb NOT NULL,
  PRIMARY KEY (request_id, company_id)
);

-- Отклик поставщика. Отдельная запись: автор заявки не теряет её при параллельных откликах
CREATE TABLE request_response (
  id         text PRIMARY KEY,
  request_id text NOT NULL,                  -- заявка могла быть снята автором, отклик остаётся в истории
  author_id  text NOT NULL,
  company    text,
  text       text,
  price      text,
  at         timestamptz NOT NULL DEFAULT now(),
  extra      jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX request_response_request ON request_response (request_id);
