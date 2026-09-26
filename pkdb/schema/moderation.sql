-- sm01_moderation — модерация: регистрации представителей, решения модератора, подтверждённые представители,
-- ручные статусы проверки, правки продукции представителями, отключённые источники, сообщения об ошибках, аудит.
-- Контакты представителя (ФИО, e-mail, телефон) здесь не хранятся: они в sm01_accounts, API подставляет их модератору.

-- Заявка на регистрацию представителя компании (снимок реквизитов, отправленный на проверку)
CREATE TABLE registration (
  user_id         text PRIMARY KEY,
  name            text,
  legal_name      text,
  inn             text,
  ogrn            text,
  kpp             text,
  okpo            text,
  okved_main      text,
  reg_date        text,
  address         text,
  postal_address  text,
  site            text,
  phone           text,              -- телефон и e-mail компании (не представителя)
  email           text,
  base_company_id text,              -- карточка каталога, из которой подставлены реквизиты
  from_base       text[] NOT NULL DEFAULT '{}',
  status          text NOT NULL DEFAULT 'PENDING',
  is_edit         boolean NOT NULL DEFAULT false,
  data_checked    boolean,
  submitted_at    timestamptz NOT NULL DEFAULT now(),
  extra           jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX registration_inn ON registration (inn);

-- Решение модератора по регистрации; относится к отправке submitted_at
CREATE TABLE registration_decision (
  user_id      text PRIMARY KEY,
  status       text NOT NULL CHECK (status IN ('APPROVED','REJECTED')),
  comment      text,
  decided_at   timestamptz NOT NULL DEFAULT now(),
  submitted_at timestamptz,
  moderator_id text,
  company_name text,
  extra        jsonb NOT NULL DEFAULT '{}'
);

-- Подтверждённые представители (без персональных данных — видны всем)
CREATE TABLE company_rep (
  user_id      text PRIMARY KEY,
  company_id   text NOT NULL,
  company_name text,
  approved_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX company_rep_company ON company_rep (company_id);

-- Статус проверки предприятия, выставленный модератором поверх данных сбора
CREATE TABLE status_override (
  company_id text PRIMARY KEY,
  status     text NOT NULL CHECK (status IN ('VERIFIED','PARTIALLY_VERIFIED','UNVERIFIED','OUTDATED')),
  note       text,
  author_id  text,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Решение по предложению или заявке: ключ <offers|requests>:<id>
CREATE TABLE item_decision (
  key          text PRIMARY KEY,
  coll         text NOT NULL CHECK (coll IN ('offers','requests')),
  item_id      text NOT NULL,
  status       text NOT NULL CHECK (status IN ('APPROVED','REJECTED')),
  comment      text,
  decided_at   timestamptz NOT NULL DEFAULT now(),
  moderator_id text
);

-- Правки продукции подтверждённым представителем поверх открытых источников. Исходные данные каталога не меняются:
-- удалённую позицию можно вернуть. Применяются только правки представителя той компании, чья это продукция
CREATE TABLE product_edit (
  user_id    text NOT NULL,
  product_id text NOT NULL,
  company_id text,
  deleted    boolean NOT NULL DEFAULT false,
  fields     jsonb,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, product_id)
);

-- Источники, отключённые администратором
CREATE TABLE source_flag (
  source_id  text PRIMARY KEY,
  disabled   boolean NOT NULL,
  at         timestamptz NOT NULL DEFAULT now(),
  author_id  text
);

-- Сообщения пользователей и служебные записи сайта: ошибка в данных, повторный обход, журнал действий модератора
CREATE TABLE report (
  id         text PRIMARY KEY,
  kind       text NOT NULL,           -- data_error, recrawl, audit, override (прежний формат)
  author_id  text,
  company_id text,
  field      text,
  text       text,
  url        text,
  status     text,
  created_at timestamptz NOT NULL DEFAULT now(),
  extra      jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX report_kind ON report (kind, created_at DESC);

-- Журнал действий через API (создание записей, смена статусов, модерация, запуск сбора)
CREATE TABLE audit_log (
  id        bigserial PRIMARY KEY,
  actor_id  text,
  action    text NOT NULL,
  entity    text,
  entity_id text,
  payload   jsonb,
  at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_at ON audit_log (at DESC);
