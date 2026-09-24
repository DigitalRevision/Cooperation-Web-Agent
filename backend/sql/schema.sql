-- Промышленная кооперация — реляционная модель (PostgreSQL 15+)
-- Принцип: каждое фактическое значение ссылается на источник (field_source), неизвестное хранится как NULL.

CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TYPE verification_status AS ENUM ('VERIFIED','PARTIALLY_VERIFIED','UNVERIFIED','OUTDATED');
CREATE TYPE relation_type AS ENUM ('CONFIRMED_RELATION','POTENTIAL_RELATION','INFERRED_RELATION');
CREATE TYPE code_status AS ENUM ('SOURCE','INFERRED','USER');
CREATE TYPE user_role AS ENUM ('user','company_admin','moderator','admin');

CREATE TABLE region (code text PRIMARY KEY, name text NOT NULL, is_pilot boolean NOT NULL DEFAULT false);
CREATE TABLE city (id serial PRIMARY KEY, name text NOT NULL, region_code text REFERENCES region, lat double precision, lon double precision, UNIQUE(name, region_code));

CREATE TABLE okved (code text PRIMARY KEY, name text NOT NULL, parent_code text REFERENCES okved);
CREATE TABLE okpd2 (code text PRIMARY KEY, name text NOT NULL, parent_code text REFERENCES okpd2);
CREATE TABLE material (id serial PRIMARY KEY, name text UNIQUE NOT NULL, grade text);
CREATE TABLE technology (id serial PRIMARY KEY, name text UNIQUE NOT NULL);

CREATE TABLE source (
  id text PRIMARY KEY,
  source_url text NOT NULL,
  source_type text NOT NULL,          -- OFFICIAL_SITE, OFFICIAL_CATALOG, EGRUL_AGGREGATOR, GISP, REGIONAL_CATALOG, INDUSTRY_CATALOG, OTHER
  source_title text NOT NULL,
  priority smallint NOT NULL,         -- 1 (официальный сайт) … 12 (прочие)
  source_date date,
  last_verified_at timestamptz,
  fetch_status text,
  is_disabled boolean NOT NULL DEFAULT false,
  note text
);

CREATE TABLE organization (
  id text PRIMARY KEY,
  name text NOT NULL, short_name text, legal_name text,
  inn varchar(12) UNIQUE, ogrn varchar(15) UNIQUE, kpp varchar(9), reg_date date, legal_status text,
  region_code text REFERENCES region, city text, address text, site text,
  phones text[] NOT NULL DEFAULT '{}', emails text[] NOT NULL DEFAULT '{}',
  industry text, subindustry text, description text,
  verification_status verification_status NOT NULL DEFAULT 'UNVERIFIED',
  last_verified_at timestamptz,
  search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('russian', coalesce(name,'')||' '||coalesce(legal_name,'')||' '||coalesce(subindustry,'')||' '||coalesce(description,''))) STORED,
  embedding vector(1024)
);
CREATE INDEX organization_tsv ON organization USING gin(search_tsv);
CREATE INDEX organization_region ON organization(region_code, verification_status);

-- Какой источник подтверждает какое поле любой сущности
CREATE TABLE field_source (
  entity_type text NOT NULL, entity_id text NOT NULL, field text NOT NULL,
  source_id text NOT NULL REFERENCES source, confirmed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (entity_type, entity_id, field, source_id)
);
CREATE TABLE discrepancy (id serial PRIMARY KEY, organization_id text REFERENCES organization, field text NOT NULL, note text, resolved boolean NOT NULL DEFAULT false);
CREATE TABLE discrepancy_value (discrepancy_id int REFERENCES discrepancy ON DELETE CASCADE, value text, source_id text REFERENCES source);

CREATE TABLE organization_okved (organization_id text REFERENCES organization, okved_code text REFERENCES okved, is_main boolean NOT NULL, source_id text REFERENCES source, PRIMARY KEY(organization_id, okved_code));
CREATE TABLE organization_technology (organization_id text REFERENCES organization, technology_id int REFERENCES technology, source_id text REFERENCES source, PRIMARY KEY(organization_id, technology_id));
CREATE TABLE organization_branch (id serial PRIMARY KEY, organization_id text REFERENCES organization, name text, kind text CHECK (kind IN ('PLANT','WORKSHOP','SITE','BRANCH')), address text, city text, region_code text REFERENCES region, lat double precision, lon double precision, area text, capacity_text text, source_id text REFERENCES source);
CREATE TABLE warehouse (id serial PRIMARY KEY, organization_id text REFERENCES organization, branch_id int REFERENCES organization_branch, name text NOT NULL, address text, city text, region_code text REFERENCES region, lat double precision, lon double precision, storage_volume numeric, storage_unit text, available_volume numeric, available_unit text, source_id text REFERENCES source, entered_by_user bigint);
CREATE TABLE capacity (id serial PRIMARY KEY, organization_id text REFERENCES organization, text text NOT NULL, value numeric, qualifier text, unit text, is_historical boolean NOT NULL DEFAULT false, source_id text NOT NULL REFERENCES source);
CREATE TABLE certificate (id serial PRIMARY KEY, organization_id text REFERENCES organization, name text NOT NULL, number text, valid_until date, source_id text REFERENCES source);
CREATE TABLE document (id serial PRIMARY KEY, organization_id text REFERENCES organization, title text, url text, s3_key text, source_id text REFERENCES source);

CREATE TABLE product (
  id text PRIMARY KEY, organization_id text NOT NULL REFERENCES organization,
  name text NOT NULL, kind text NOT NULL CHECK (kind IN ('product','service')), category text, description text,
  photo_s3_key text, source_id text NOT NULL REFERENCES source, last_verified_at timestamptz,
  search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('russian', coalesce(name,'')||' '||coalesce(category,'')||' '||coalesce(description,''))) STORED,
  embedding vector(1024)
);
CREATE INDEX product_tsv ON product USING gin(search_tsv);
CREATE INDEX product_name_trgm ON product USING gin(name gin_trgm_ops);
CREATE TABLE product_specification (id serial PRIMARY KEY, product_id text REFERENCES product ON DELETE CASCADE, name text NOT NULL, value text, unit text, source_id text REFERENCES source);
CREATE TABLE product_okpd2 (product_id text REFERENCES product ON DELETE CASCADE, okpd2_code text REFERENCES okpd2, status code_status NOT NULL, source_id text REFERENCES source, PRIMARY KEY(product_id, okpd2_code));
CREATE TABLE product_material (product_id text REFERENCES product ON DELETE CASCADE, material_id int REFERENCES material, source_id text REFERENCES source, PRIMARY KEY(product_id, material_id));
CREATE TABLE product_technology (product_id text REFERENCES product ON DELETE CASCADE, technology_id int REFERENCES technology, source_id text REFERENCES source, PRIMARY KEY(product_id, technology_id));

CREATE TABLE app_user (id bigserial PRIMARY KEY, email text UNIQUE NOT NULL, password_hash text NOT NULL, full_name text, role user_role NOT NULL DEFAULT 'user', city text, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE user_organization (user_id bigint REFERENCES app_user, organization_id text REFERENCES organization, role text, status text NOT NULL DEFAULT 'PENDING', PRIMARY KEY(user_id, organization_id));

-- Цена всегда со всеми атрибутами; NULL value = «Цена по запросу»
CREATE TABLE offer (
  id bigserial PRIMARY KEY, author_id bigint REFERENCES app_user, organization_id text REFERENCES organization, product_id text REFERENCES product,
  title text NOT NULL, category text NOT NULL, description text, material text, okpd2_code text REFERENCES okpd2, specs jsonb,
  quantity numeric, unit text, price_value numeric, price_currency char(3), price_unit text, price_min_qty numeric, price_date date, price_source text CHECK (price_source IN ('SELLER','OPEN_SOURCE')),
  min_batch text, lead_time_production text, lead_time_delivery text, warehouse_id int REFERENCES warehouse, city text, region_code text REFERENCES region,
  delivery_terms text, documents text, moderation_status text NOT NULL DEFAULT 'NEW', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE purchase_request (
  id bigserial PRIMARY KEY, author_id bigint REFERENCES app_user, organization_id text REFERENCES organization, target_organization_id text REFERENCES organization,
  what text NOT NULL, quantity numeric, unit text, period text, material text, specs text, okpd2_code text REFERENCES okpd2, required_certificates text,
  deadline date, region_code text REFERENCES region, city text, max_distance_km int, budget numeric, extra text, parsed_query jsonb,
  moderation_status text NOT NULL DEFAULT 'NEW', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE supplier (request_id bigint REFERENCES purchase_request ON DELETE CASCADE, organization_id text REFERENCES organization, match jsonb NOT NULL, confirmed_count int, applicable_count int, PRIMARY KEY(request_id, organization_id));
CREATE TABLE supplier_offer (id bigserial PRIMARY KEY, request_id bigint REFERENCES purchase_request ON DELETE CASCADE, organization_id text REFERENCES organization, author_id bigint REFERENCES app_user, text text, price_value numeric, price_unit text, created_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE production_chain (id bigserial PRIMARY KEY, owner_id bigint REFERENCES app_user, title text NOT NULL, buyer_city text, created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now());
CREATE TABLE production_chain_node (id bigserial PRIMARY KEY, chain_id bigint REFERENCES production_chain ON DELETE CASCADE, position int NOT NULL, step text NOT NULL, requirement text, organization_id text REFERENCES organization, product_id text REFERENCES product, status text NOT NULL DEFAULT 'EMPTY' CHECK (status IN ('EMPTY','SELECTED','DECLINED','CONFIRMED')));
CREATE TABLE production_chain_node_history (id bigserial PRIMARY KEY, node_id bigint REFERENCES production_chain_node ON DELETE CASCADE, from_org text, to_org text, reason text, at timestamptz DEFAULT now());
CREATE TABLE production_chain_edge (
  id bigserial PRIMARY KEY, chain_id bigint REFERENCES production_chain ON DELETE CASCADE,
  from_node bigint REFERENCES production_chain_node ON DELETE CASCADE, to_node bigint REFERENCES production_chain_node ON DELETE CASCADE,
  relation relation_type NOT NULL DEFAULT 'INFERRED_RELATION', product_id text REFERENCES product, material text, okpd2_code text, okved_code text, technology text,
  quantity numeric, unit text, price_value numeric, price_unit text, min_batch text, lead_time_production text, lead_time_delivery text,
  region_code text, warehouse_id int REFERENCES warehouse, source_id text REFERENCES source
);
CREATE TABLE organization_relation (id text PRIMARY KEY, from_org text REFERENCES organization, from_product text REFERENCES product, to_org text REFERENCES organization, to_product text REFERENCES product, relation relation_type NOT NULL, basis text NOT NULL);

CREATE TABLE crawl_job (id bigserial PRIMARY KEY, url text NOT NULL, organization_id text REFERENCES organization, status text NOT NULL DEFAULT 'QUEUED', scheduled_at timestamptz DEFAULT now(), started_at timestamptz, finished_at timestamptz, attempts int DEFAULT 0);
CREATE TABLE crawl_result (id bigserial PRIMARY KEY, job_id bigint REFERENCES crawl_job, url text NOT NULL, http_status int, fetch_status text, fetched_at timestamptz, content_hash text, extracted_text text, extracted jsonb, error text);
CREATE INDEX crawl_result_hash ON crawl_result(content_hash);

CREATE TABLE review (id bigserial PRIMARY KEY, organization_id text REFERENCES organization, author_id bigint REFERENCES app_user, supplier_offer_id bigint REFERENCES supplier_offer NOT NULL, text text, created_at timestamptz DEFAULT now()); -- только после подтверждённого взаимодействия
CREATE TABLE message (id bigserial PRIMARY KEY, thread_request_id bigint REFERENCES purchase_request, sender_id bigint REFERENCES app_user, text text NOT NULL, created_at timestamptz DEFAULT now());
CREATE TABLE favorite (user_id bigint REFERENCES app_user, entity_type text, entity_id text, PRIMARY KEY(user_id, entity_type, entity_id));
CREATE TABLE comparison (user_id bigint REFERENCES app_user, entity_type text, entity_id text, position int, PRIMARY KEY(user_id, entity_type, entity_id));
CREATE TABLE saved_search (id bigserial PRIMARY KEY, user_id bigint REFERENCES app_user, text text, parsed jsonb, created_at timestamptz DEFAULT now());
CREATE TABLE ai_query (id bigserial PRIMARY KEY, user_id bigint REFERENCES app_user, raw text NOT NULL, parsed jsonb, engine text, result_ids text[], created_at timestamptz DEFAULT now());
CREATE TABLE complaint (id bigserial PRIMARY KEY, author_id bigint REFERENCES app_user, organization_id text REFERENCES organization, field text, text text, status text DEFAULT 'OPEN', created_at timestamptz DEFAULT now());
CREATE TABLE audit_log (id bigserial PRIMARY KEY, actor_id bigint, action text NOT NULL, entity_type text, entity_id text, before jsonb, after jsonb, at timestamptz NOT NULL DEFAULT now());
