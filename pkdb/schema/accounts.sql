-- sm01_accounts — пользователи и личный кабинет. Здесь и только здесь лежат персональные данные (152-ФЗ):
-- ФИО, должность, e-mail и телефон представителей, контакты мессенджеров. Сбор данных (sync) доступа к этой базе не имеет.

CREATE TABLE app_user (
  id           text PRIMARY KEY,                -- случайный идентификатор; для служебных токенов — staff-<хеш>
  role         text NOT NULL DEFAULT 'user' CHECK (role IN ('user','company_admin','moderator','admin')),
  kind         text NOT NULL DEFAULT 'session' CHECK (kind IN ('session','staff','legacy')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now()
);

-- Сессии браузера: в базе только SHA-256 токена, сам токен знает лишь браузер
CREATE TABLE user_session (
  token_hash   text PRIMARY KEY,
  user_id      text NOT NULL REFERENCES app_user ON DELETE CASCADE,
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_used_at timestamptz NOT NULL DEFAULT now(),
  user_agent   text
);
CREATE INDEX user_session_user ON user_session (user_id);

-- Учётная запись представителя (персональные данные)
CREATE TABLE user_account (
  user_id       text PRIMARY KEY REFERENCES app_user ON DELETE CASCADE,
  fio           text,
  position      text,
  email         text,
  phone         text,
  consent_at    timestamptz,                    -- согласие на обработку персональных данных
  registered_at timestamptz,
  extra         jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX user_account_email ON user_account (lower(email));

-- Профиль: город для расчёта расстояний, выход из кабинета, служебное состояние ленты уведомлений
CREATE TABLE user_profile (
  user_id    text PRIMARY KEY REFERENCES app_user ON DELETE CASCADE,
  city       text,
  signed_out boolean NOT NULL DEFAULT false,
  seen       jsonb,                             -- какие события лента уже учла (заявки, отклики, риски, решения)
  extra      jsonb NOT NULL DEFAULT '{}',
  updated_at timestamptz NOT NULL DEFAULT now()
);

-- Компания пользователя, как он её видит в кабинете (реквизиты и состояние проверки)
CREATE TABLE user_company (
  user_id           text PRIMARY KEY REFERENCES app_user ON DELETE CASCADE,
  name              text,
  legal_name        text,
  inn               text,
  ogrn              text,
  kpp               text,
  okpo              text,
  okved_main        text,
  reg_date          text,
  address           text,
  postal_address    text,
  site              text,
  phone             text,
  email             text,
  base_company_id   text,                       -- карточка каталога (sm01_catalog.company.id), проверяется приложением
  from_base         text[] NOT NULL DEFAULT '{}',
  status            text,
  submitted_at      timestamptz,
  updated_at        timestamptz,
  moderator_comment text,
  decided_at        timestamptz,
  extra             jsonb NOT NULL DEFAULT '{}'
);

-- Избранное и сравнение: c:<id предприятия>, p:<id позиции>, o:<id предложения>
CREATE TABLE user_favorite (
  user_id text NOT NULL REFERENCES app_user ON DELETE CASCADE, pos int NOT NULL, entity text NOT NULL,
  PRIMARY KEY (user_id, pos)
);
CREATE TABLE user_compare (
  user_id text NOT NULL REFERENCES app_user ON DELETE CASCADE, pos int NOT NULL, entity text NOT NULL,
  PRIMARY KEY (user_id, pos)
);
CREATE TABLE saved_search (
  user_id text NOT NULL REFERENCES app_user ON DELETE CASCADE, pos int NOT NULL,
  text text NOT NULL, at timestamptz, extra jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (user_id, pos)
);

-- «Мои предприятия»: привязка к карточкам каталога, ожидает подтверждения модератором
CREATE TABLE company_claim (
  user_id    text NOT NULL REFERENCES app_user ON DELETE CASCADE,
  company_id text NOT NULL,
  pos        int  NOT NULL,
  role       text,
  status     text,
  extra      jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (user_id, company_id)
);

-- Склады и площадки, указанные пользователем
CREATE TABLE warehouse (
  user_id   text NOT NULL REFERENCES app_user ON DELETE CASCADE,
  id        text NOT NULL,
  pos       int  NOT NULL,
  name      text,
  type      text,
  address   text,
  city      text,
  capacity  text,
  available text,
  extra     jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (user_id, id)
);

-- Уведомления: каналы (Telegram, ВКонтакте) и переключатели событий
CREATE TABLE notify_channel (
  user_id text NOT NULL REFERENCES app_user ON DELETE CASCADE,
  channel text NOT NULL CHECK (channel IN ('telegram','vk')),
  enabled boolean NOT NULL DEFAULT false,
  contact text NOT NULL DEFAULT '',
  PRIMARY KEY (user_id, channel)
);
CREATE TABLE notify_event (
  user_id text NOT NULL REFERENCES app_user ON DELETE CASCADE,
  event   text NOT NULL,
  channel text NOT NULL CHECK (channel IN ('telegram','vk')),
  enabled boolean NOT NULL,
  PRIMARY KEY (user_id, event, channel)
);

-- Лента уведомлений на сайте (новые первыми, не больше 200)
CREATE TABLE inbox_notice (
  user_id text NOT NULL REFERENCES app_user ON DELETE CASCADE,
  id      text NOT NULL,
  event   text,
  title   text,
  text    text,
  link    text,
  at      timestamptz NOT NULL DEFAULT now(),
  read    boolean NOT NULL DEFAULT false,
  via     jsonb NOT NULL DEFAULT '[]',          -- куда ушла копия и с каким результатом
  PRIMARY KEY (user_id, id)
);
CREATE INDEX inbox_notice_unread ON inbox_notice (user_id, at DESC) WHERE NOT read;

-- Telegram: бот может писать только тем, кто нажал /start. @username → chat_id из вебхука
CREATE TABLE telegram_link (
  username  text PRIMARY KEY,
  chat_id   bigint NOT NULL,
  linked_at timestamptz NOT NULL DEFAULT now()
);
