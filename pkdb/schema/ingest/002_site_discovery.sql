-- Поиск официальных сайтов предприятий краулером: какие домены проверены и чем подтверждены.
-- CONFIRMED — на сайте ИНН или ОГРН предприятия либо его название вместе с адресом из ЕГРЮЛ: сайт обходится и записывается
-- в карточку (tools/crawl_products.py auto); CANDIDATE — совпало только название: сайт ждёт решения модератора.
CREATE TABLE site_discovery (
  company_id  text NOT NULL,
  domain      text NOT NULL,
  url         text NOT NULL,                -- главная страница после перенаправлений
  method      text NOT NULL,                -- guess — домен по названию; email — домен корпоративной почты; search — поисковик
  status      text NOT NULL CHECK (status IN ('CONFIRMED', 'CANDIDATE', 'REJECTED')),
  evidence    jsonb,                        -- {"by": "inn", "page": "https://…/contacts", "name": true, "address": true, "city": true}
  checked_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (company_id, domain)
);
CREATE INDEX site_discovery_status ON site_discovery (status, checked_at DESC);

-- Когда у предприятия последний раз искали сайт: повторный поиск — не раньше чем через PK_DISCOVER_RECHECK_DAYS дней
CREATE TABLE site_search (
  company_id  text PRIMARY KEY,
  searched_at timestamptz NOT NULL DEFAULT now(),
  candidates  int NOT NULL DEFAULT 0,       -- сколько доменов проверено
  found       text                          -- подтверждённый сайт или NULL
);
