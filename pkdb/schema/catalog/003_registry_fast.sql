-- Компании быстрого добавления (python -m sync --fast): заведены из строк поиска ГИР БО, без запросов к ЕГРЮЛ и «Прозрачному бизнесу».
-- Своя метка происхождения: API держит в памяти только «ядро» каталога (pkdb/catalog.py, CORE_SQL), а такие карточки без продукции
-- и сайта читает из базы по запросу. Отличить их можно по источникам: у добавленных обычным сбором есть ЕГРЮЛ или «Прозрачный бизнес»
UPDATE company c SET origin = 'registry_fast'
 WHERE origin = 'registry_sync'
   AND NOT EXISTS (SELECT 1 FROM source s WHERE s.company_id = c.id AND s.source_type IN ('FNS_EGRUL', 'FNS_PB'));
UPDATE catalog_revision SET revision = revision + 1, updated_at = now(), note = 'метка registry_fast';
