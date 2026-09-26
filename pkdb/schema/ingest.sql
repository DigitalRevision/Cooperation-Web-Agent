-- sm01_ingest — сбор данных: запуски синхронизации с реестрами, их журналы, управление запуском, обход сайтов.
-- Пишут: sync и краулер; API читает состояние и ставит запрос ручного запуска (кнопка в админ-панели).
-- Заменяет файлы data/sync/*.json, run.lock, status.json, run-request.json и data/sources/crawl_log_*.json.

-- Один проход синхронизации
CREATE TABLE sync_run (
  id          bigserial PRIMARY KEY,
  name        text UNIQUE NOT NULL,       -- 2026-09-26_0119: дата и время начала, как имя прежнего файла журнала
  started_at  timestamptz NOT NULL,
  finished_at timestamptz,
  trigger     text,
  regions     text[] NOT NULL DEFAULT '{}',
  found       int,
  queued_new  int,
  requests    int,
  stats       jsonb NOT NULL DEFAULT '{}',   -- checked, added, updated, closed, risks_added, failed
  extra       jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX sync_run_started ON sync_run (started_at DESC);

-- Изменения, найденные проходом
CREATE TABLE sync_change (
  run_id     bigint NOT NULL REFERENCES sync_run ON DELETE CASCADE,
  pos        int    NOT NULL,
  date       date,
  company_id text,
  inn        text,
  name       text,
  kind       text NOT NULL,              -- added, updated, status, risk_added, risk_removed
  field      text,
  old        text,
  new        text,
  PRIMARY KEY (run_id, pos)
);
CREATE INDEX sync_change_company ON sync_change (company_id);

-- Ошибки источников (не больше 500 на проход)
CREATE TABLE sync_error (
  run_id bigint NOT NULL REFERENCES sync_run ON DELETE CASCADE,
  pos    int    NOT NULL,
  source text,
  place  text,                           -- где: «ИНН …», «поиск Волгоградская область, ОКВЭД 28»
  error  text,
  PRIMARY KEY (run_id, pos)
);

-- Состояние сбора для админ-панели: планировщик жив, этап, сколько проверено, итоги последнего запуска
CREATE TABLE sync_state (
  id         int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  status     jsonb NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO sync_state DEFAULT VALUES;

-- Блокировка запуска: два прохода одновременно испортили бы базу. Запись с heartbeat_at старше 10 минут —
-- процесс сбора завершился аварийно, такую блокировку можно занять
CREATE TABLE sync_lock (
  id           int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  holder       jsonb NOT NULL,
  acquired_at  timestamptz NOT NULL DEFAULT now(),
  heartbeat_at timestamptz NOT NULL DEFAULT now()
);

-- Запросы ручного запуска (кнопка «Запустить сбор сейчас»); планировщик забирает их в течение 15 секунд
CREATE TABLE sync_request (
  id           bigserial PRIMARY KEY,
  requested_by text,
  requested_at timestamptz NOT NULL DEFAULT now(),
  taken_at     timestamptz
);
CREATE INDEX sync_request_pending ON sync_request (requested_at) WHERE taken_at IS NULL;

-- Журнал обхода сайтов краулером: по каждому URL за день остаётся последний результат
CREATE TABLE crawl_log (
  id         bigserial PRIMARY KEY,
  day        date NOT NULL,
  pos        int  NOT NULL DEFAULT 0,
  url        text NOT NULL,
  status     text,
  note       text,
  fetched_at date,
  UNIQUE (day, url)
);

-- Сырые результаты обхода (раньше data/crawl/<компания>/<дата>.jsonl). В карточку факты переносит модератор
CREATE TABLE crawl_page (
  id           bigserial PRIMARY KEY,
  company_id   text,
  url          text NOT NULL,
  fetched_at   timestamptz NOT NULL DEFAULT now(),
  fetch_status text,
  content_hash text,
  item         jsonb NOT NULL
);
CREATE INDEX crawl_page_company ON crawl_page (company_id, fetched_at DESC);
CREATE INDEX crawl_page_hash ON crawl_page (content_hash);

-- Очередь задач обхода, поставленных из админ-панели
CREATE TABLE crawl_job (
  id              text PRIMARY KEY,
  url             text NOT NULL,
  organization_id text,
  status          text NOT NULL DEFAULT 'QUEUED',
  requested_by    text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
