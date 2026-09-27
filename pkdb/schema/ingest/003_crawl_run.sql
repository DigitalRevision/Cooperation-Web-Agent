-- Запуски краулера (crawler/daemon.py): nightly — после каждого сбора из реестров (sync, ежедневно в PK_SYNC_AT), поиск сайтов
-- и обход всех известных сайтов; jobs — задания повторного обхода из админ-панели (crawl_job). Когда запуск закончен (OK),
-- планировщик сбора сразу переносит найденное в карточки и отмечает applied_at: следующей ночи ждать не нужно.
CREATE TABLE crawl_run (
  id          bigserial PRIMARY KEY,
  kind        text NOT NULL CHECK (kind IN ('nightly', 'jobs')),
  started_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  status      text NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING', 'OK', 'FAILED')),
  stats       jsonb,                        -- {"pages": …, "searched": …, "sites_confirmed": …, "sites_candidates": …, "jobs": …}
  error       text,
  applied_at  timestamptz,                  -- найденное перенесено в карточки (sync)
  applied     jsonb                         -- {"sites": …, "products": …}
);
CREATE INDEX crawl_run_started ON crawl_run (started_at DESC);

-- Очередь повторного обхода: QUEUED → RUNNING (краулер взял) → DONE или FAILED (с пояснением в note)
ALTER TABLE crawl_job ADD COLUMN taken_at timestamptz;
ALTER TABLE crawl_job ADD COLUMN done_at timestamptz;
ALTER TABLE crawl_job ADD COLUMN note text;
