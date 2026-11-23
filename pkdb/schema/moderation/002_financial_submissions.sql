-- Заявленная предприятием структура выручки и решение модератора.
CREATE TABLE financial_submission (
  id            uuid PRIMARY KEY,
  user_id       text NOT NULL,
  company_id    text NOT NULL,
  report_year   smallint NOT NULL CHECK (report_year BETWEEN 1990 AND 2100),
  scope         text NOT NULL CHECK (scope IN ('entity','consolidated','unknown')),
  document_url  text NOT NULL,
  activities    jsonb NOT NULL CHECK (jsonb_typeof(activities) = 'array'),
  status        text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','APPROVED','REJECTED')),
  comment       text,
  submitted_at  timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  moderator_id  text,
  decided_at    timestamptz,
  UNIQUE (user_id, company_id, report_year, id)
);
CREATE INDEX financial_submission_pending ON financial_submission (submitted_at) WHERE status = 'PENDING';
CREATE INDEX financial_submission_company_year ON financial_submission (company_id, report_year, updated_at DESC);
