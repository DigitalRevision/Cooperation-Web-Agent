-- sm01_catalog — каталог предприятий: реквизиты, продукция, источники, риски, отчётность.
-- Пишут: сбор из реестров (sync), краулер, загрузка из JSON. Читает: API (роль только на чтение).
-- Принцип платформы: у каждого факта есть источник (source_id), неизвестное хранится как NULL.
-- Поля, которых нет в схеме, не теряются: они попадают в столбец extra (jsonb) своей таблицы.

CREATE TABLE region (
  code     text PRIMARY KEY,
  name     text NOT NULL,
  is_pilot boolean NOT NULL DEFAULT false
);

-- Центры городов: только для расчёта расстояния «по прямой между городами»
CREATE TABLE city (
  name text PRIMARY KEY,
  lat  double precision NOT NULL,
  lon  double precision NOT NULL,
  note text
);

-- Название кода может быть неизвестно (реестр отдал код без названия): тогда NULL, а не выдуманный текст
CREATE TABLE okved (code text PRIMARY KEY, name text);
CREATE TABLE okpd2 (code text PRIMARY KEY, name text NOT NULL);
-- Справочники материалов и технологий, встреченных в источниках
CREATE TABLE material (name text PRIMARY KEY);
CREATE TABLE technology (name text PRIMARY KEY);

CREATE TABLE company (
  id                  text PRIMARY KEY,
  name                text NOT NULL,
  short_name          text,
  legal_name          text,
  inn                 varchar(12) CHECK (inn ~ '^(\d{10}|\d{12})$'),
  ogrn                varchar(15) CHECK (ogrn ~ '^(\d{13}|\d{15})$'),
  kpp                 varchar(9),
  okpo                varchar(10),
  reg_date            date,
  legal_status        text,
  status_code         text CHECK (status_code IN ('ACTIVE','REORGANIZING','LIQUIDATING','BANKRUPTCY','LIQUIDATED')),
  region_code         text REFERENCES region,
  city                text,
  address             text,
  site                text,
  phones              text[] NOT NULL DEFAULT '{}',
  emails              text[] NOT NULL DEFAULT '{}',
  okved_main          text REFERENCES okved,
  industry            text,
  subindustry         text,
  description         text,
  verification_status text NOT NULL DEFAULT 'UNVERIFIED'
                      CHECK (verification_status IN ('VERIFIED','PARTIALLY_VERIFIED','UNVERIFIED','OUTDATED')),
  origin              text,                 -- registry_sync — добавлена сбором из реестров; NULL — первичный сбор
  added_at            date,
  ro_member           boolean,              -- участник регионального отделения Союза машиностроителей
  -- состояние сверки с реестрами (показывается на сайте: «сверено с реестрами …»)
  sync_checked_at     date,
  sync_status_by      text[],               -- источники, на которых держится статус юрлица
  sync_sources        jsonb,                -- источник → OK / NOT_FOUND / текст ошибки последнего запуска
  girbo_id            text,
  extra               jsonb NOT NULL DEFAULT '{}',
  updated_at          timestamptz NOT NULL DEFAULT now(),
  search_tsv          tsvector GENERATED ALWAYS AS (
                        to_tsvector('russian', coalesce(name,'') || ' ' || coalesce(legal_name,'') || ' ' ||
                                               coalesce(subindustry,'') || ' ' || coalesce(description,''))) STORED
);
-- ИНН не уникален: филиал заводится отдельной карточкой с ИНН головной компании
CREATE INDEX company_inn ON company (inn);
CREATE INDEX company_region_status ON company (region_code, verification_status);
CREATE INDEX company_okved_main ON company (okved_main);
CREATE INDEX company_tsv ON company USING gin (search_tsv);

-- Дополнительные коды ОКВЭД (порядок — как в реестре)
CREATE TABLE company_okved (
  company_id text NOT NULL REFERENCES company ON DELETE CASCADE,
  okved_code text NOT NULL REFERENCES okved,
  pos        int  NOT NULL,
  PRIMARY KEY (company_id, okved_code)
);
CREATE INDEX company_okved_code ON company_okved (okved_code);

-- Источники данных карточки. Приоритет: 1 — официальный сайт … 12 — прочие
CREATE TABLE source (
  id               text PRIMARY KEY,
  company_id       text NOT NULL REFERENCES company ON DELETE CASCADE,
  pos              int  NOT NULL,
  source_url       text,
  source_type      text NOT NULL,
  source_title     text,
  priority         smallint,
  source_date      date,
  last_verified_at date,
  confirms         text[],
  fetch_status     text,
  note             text,
  extra            jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX source_company ON source (company_id);
CREATE INDEX source_problems ON source (fetch_status) WHERE fetch_status IS DISTINCT FROM 'OK';

-- Факты карточки со ссылкой на источник
CREATE TABLE company_technology (
  company_id text NOT NULL REFERENCES company ON DELETE CASCADE, pos int NOT NULL,
  name text NOT NULL, source_id text, extra jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (company_id, pos)
);
CREATE TABLE company_material (
  company_id text NOT NULL REFERENCES company ON DELETE CASCADE, pos int NOT NULL,
  name text NOT NULL, source_id text, extra jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (company_id, pos)
);
CREATE TABLE company_capacity (
  company_id text NOT NULL REFERENCES company ON DELETE CASCADE, pos int NOT NULL,
  text text NOT NULL, value numeric, qualifier text, unit text, historical boolean,
  source_id text, extra jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (company_id, pos)
);
CREATE TABLE company_certificate (
  company_id text NOT NULL REFERENCES company ON DELETE CASCADE, pos int NOT NULL,
  name text NOT NULL, source_id text, extra jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (company_id, pos)
);
-- Производственные площадки
CREATE TABLE company_site (
  company_id text NOT NULL REFERENCES company ON DELETE CASCADE, pos int NOT NULL,
  name text, type text, address text, area text, source_id text, extra jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (company_id, pos)
);
-- Возможности, заявленные кодами ОКВЭД ЕГРЮЛ (не подтверждение производства)
CREATE TABLE company_capability (
  company_id text NOT NULL REFERENCES company ON DELETE CASCADE, pos int NOT NULL,
  name text NOT NULL, okved text[] NOT NULL DEFAULT '{}',
  PRIMARY KEY (company_id, pos)
);

-- Расхождения между источниками
CREATE TABLE company_discrepancy (
  company_id text NOT NULL REFERENCES company ON DELETE CASCADE, pos int NOT NULL,
  field text NOT NULL, note text, extra jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (company_id, pos)
);
CREATE TABLE company_discrepancy_value (
  company_id text NOT NULL, discrepancy_pos int NOT NULL, pos int NOT NULL,
  value text, source_id text,
  PRIMARY KEY (company_id, discrepancy_pos, pos),
  FOREIGN KEY (company_id, discrepancy_pos) REFERENCES company_discrepancy ON DELETE CASCADE
);

-- Сигналы риска по реестрам (sync/risks.py)
CREATE TABLE company_risk_signal (
  company_id text NOT NULL REFERENCES company ON DELETE CASCADE,
  code       text NOT NULL,
  pos        int  NOT NULL,
  level      text NOT NULL CHECK (level IN ('high','mid','low')),
  title      text NOT NULL,
  text       text,
  source_key text,                -- ключ источника в сборе: pb, girbo, opendata, fedresurs, checko
  source_id  text,
  extra      jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (company_id, code)
);
CREATE INDEX company_risk_level ON company_risk_signal (level);

-- Показатели из реестров ФНС (одна строка на компанию)
CREATE TABLE company_registry (
  company_id      text PRIMARY KEY REFERENCES company ON DELETE CASCADE,
  arrears         numeric,        -- недоимка, пени и штрафы, ₽
  arrears_date    date,
  tax_mode        text,
  headcount       int,
  headcount_year  int,
  taxes_paid      numeric,
  taxes_year      int,
  msp             text,
  capital         numeric,
  head_name       text,
  head_position   text,
  checked_at      date,
  deep_checked_at date,
  source_ids      jsonb,          -- ключ источника (pb, girbo, opendata) → id записи source
  extra           jsonb NOT NULL DEFAULT '{}'
);
-- Бухгалтерская отчётность ГИР БО, тыс. ₽
CREATE TABLE company_finance (
  company_id text NOT NULL REFERENCES company ON DELETE CASCADE,
  year       int  NOT NULL,
  pos        int  NOT NULL,
  revenue    numeric, net_profit numeric, assets numeric, equity numeric,
  PRIMARY KEY (company_id, year)
);

-- История изменений карточки (последние 30, новые первыми)
CREATE TABLE company_history (
  company_id text NOT NULL REFERENCES company ON DELETE CASCADE,
  pos        int  NOT NULL,
  date       date,
  kind       text NOT NULL,
  field      text,
  old        text,
  new        text,
  PRIMARY KEY (company_id, pos)
);

-- Продукция и производственные услуги
CREATE TABLE product (
  id                   text PRIMARY KEY,
  company_id           text NOT NULL REFERENCES company ON DELETE CASCADE,
  pos                  int  NOT NULL,
  name                 text NOT NULL,
  kind                 text NOT NULL CHECK (kind IN ('product','service')),
  category             text,
  description          text,
  okpd2_code           text REFERENCES okpd2,
  okpd2_status         text,          -- SOURCE — указан в источнике, INFERRED — присвоен по классификатору, COMPANY — подтвердило предприятие
  -- цена всегда со всеми атрибутами; NULL = «Цена по запросу»
  price_value          numeric,
  price_currency       text,
  price_unit           text,
  price_date           date,
  price_source_id      text,
  volume               text,
  min_batch            text,
  lead_time_production text,
  lead_time_delivery   text,
  availability         text,
  warehouse_id         text,
  photo                text,
  source_id            text NOT NULL,
  last_verified_at     date,
  extra                jsonb NOT NULL DEFAULT '{}',
  search_tsv           tsvector GENERATED ALWAYS AS (
                         to_tsvector('russian', coalesce(name,'') || ' ' || coalesce(category,'') || ' ' || coalesce(description,''))) STORED
);
CREATE INDEX product_company ON product (company_id);
CREATE INDEX product_okpd2 ON product (okpd2_code);
CREATE INDEX product_tsv ON product USING gin (search_tsv);

CREATE TABLE product_param (
  product_id text NOT NULL REFERENCES product ON DELETE CASCADE, pos int NOT NULL,
  name text NOT NULL, value text,
  PRIMARY KEY (product_id, pos)
);
CREATE TABLE product_material (
  product_id text NOT NULL REFERENCES product ON DELETE CASCADE, pos int NOT NULL,
  name text NOT NULL, source_id text,
  PRIMARY KEY (product_id, pos)
);

-- Связи между предприятиями и позициями (входной материал → изделие)
CREATE TABLE relation (
  id           text PRIMARY KEY,
  from_company text NOT NULL REFERENCES company ON DELETE CASCADE,
  from_product text REFERENCES product ON DELETE SET NULL,
  to_company   text NOT NULL REFERENCES company ON DELETE CASCADE,
  to_product   text REFERENCES product ON DELETE SET NULL,
  type         text NOT NULL CHECK (type IN ('CONFIRMED_RELATION','POTENTIAL_RELATION','INFERRED_RELATION')),
  basis        text NOT NULL,
  pos          int  NOT NULL DEFAULT 0
);

-- Ревизия данных: растёт при каждой записи сбора. API перечитывает каталог, когда ревизия изменилась,
-- и отдаёт её браузеру как ETag: пока база не менялась, повторный заход не скачивает каталог заново
CREATE TABLE catalog_revision (
  id         int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  revision   bigint NOT NULL DEFAULT 1,
  updated_at timestamptz NOT NULL DEFAULT now(),
  note       text
);
INSERT INTO catalog_revision DEFAULT VALUES;
