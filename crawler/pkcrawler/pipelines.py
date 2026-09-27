"""Нормализация, дедупликация, проверка источника и запись результатов в базу sm01_ingest (PostgreSQL).

Краулер НЕ изменяет карточки каталога (sm01_catalog, только чтение). Сырые результаты обхода записываются в таблицу
crawl_page, журнал обхода — в crawl_log, найденные сайты — в site_discovery и site_search. В карточку их переносит
tools/crawl_products.py auto (роль сбора). Файлов и коммитов в Git нет.
"""
import re, sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from scrapy.exceptions import DropItem

from .items import PageItem, SearchItem, SiteItem

# пакет доступа к базам (pkdb): в Docker лежит рядом, при запуске из репозитория — в корне проекта
_root = Path(__file__).resolve().parents[2]
if (_root / "pkdb").is_dir() and str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
from pkdb import connect  # noqa: E402
from pkdb import ingest  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402


class NormalizePipeline:
    def process_item(self, item, spider=None):
        if isinstance(item, PageItem) and item.get("extracted"):
            ex = item["extracted"]
            ex["phones"] = sorted({re.sub(r"[^\d+]", "", p) for p in ex["phones"]})
            ex["emails"] = sorted({e.lower().rstrip(".") for e in ex["emails"]})
        return item


class DedupPipeline:
    def __init__(self):
        self.seen = set()

    def process_item(self, item, spider=None):
        if not isinstance(item, PageItem):
            return item
        key = item.get("content_hash") or item["url"]
        if key in self.seen:
            raise DropItem(f"duplicate {item['url']}")
        self.seen.add(key)
        return item


def host(url: str | None) -> str:
    h = (urlparse(url or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


class SourceValidationPipeline:
    """Страница должна быть на домене источника из sources.yaml; ИНН сверяется с карточкой предприятия в каталоге.

    Если сайт перенаправил на чужой домен, содержимое не сохраняется: в журнал попадает статус OFFSITE_REDIRECT.
    """
    def open_spider(self, spider=None):
        with connect("catalog") as c:
            self.inn = {r["id"]: r["inn"] for r in c.execute("SELECT id, inn FROM company")}

    def process_item(self, item, spider=None):
        if not isinstance(item, PageItem):
            return item
        item["domain"] = host(item["url"])
        if item.get("source_url") and item["domain"] != host(item["source_url"]):
            item.update(fetch_status="OFFSITE_REDIRECT", text=None, extracted=None, content_hash=None)
            return item
        if item.get("extracted") and item["extracted"]["inn"]:
            inn = self.inn.get(item["company_id"])
            item["extracted"]["inn_matches_card"] = inn in item["extracted"]["inn"] if inn else None
        return item


class PostgresPipeline:
    """Результаты обхода — в sm01_ingest.crawl_page, журнал за день — в crawl_log (по каждому URL последний результат)."""
    def open_spider(self, spider=None):
        self.day = date.today().isoformat()
        self.log = []
        self.written = 0
        self.conn = connect("ingest")

    def process_item(self, item, spider=None):
        d = dict(item)
        if isinstance(item, SiteItem):
            self.conn.execute("""INSERT INTO site_discovery (company_id, domain, url, method, status, evidence) VALUES (%s,%s,%s,%s,%s,%s)
                                 ON CONFLICT (company_id, domain) DO UPDATE SET url = EXCLUDED.url, method = EXCLUDED.method,
                                 status = EXCLUDED.status, evidence = EXCLUDED.evidence, checked_at = now()""",
                              (d["company_id"], d["domain"], d["url"], d["method"], d["status"], Jsonb(d.get("evidence"))))
            self.conn.commit()
            return item
        if isinstance(item, SearchItem):
            self.conn.execute("""INSERT INTO site_search (company_id, candidates, found) VALUES (%s,%s,%s)
                                 ON CONFLICT (company_id) DO UPDATE SET searched_at = now(), candidates = EXCLUDED.candidates, found = EXCLUDED.found""",
                              (d["company_id"], d.get("candidates") or 0, d.get("found")))
            self.conn.commit()
            return item
        self.conn.execute("INSERT INTO crawl_page (company_id, url, fetch_status, content_hash, item) VALUES (%s,%s,%s,%s,%s)",
                          (d.get("company_id"), d["url"], d.get("fetch_status"), d.get("content_hash"), Jsonb(d)))
        self.conn.commit()
        self.log.append({"url": d["url"], "status": d["fetch_status"], "note": d.get("source_title"), "fetched_at": self.day})
        if len(self.log) >= 500:   # журнал — порциями: обход тысяч сайтов идёт часами, и оборванный запуск не теряет журнал
            self.flush()
        return item

    def flush(self):
        if self.log:
            ingest.write_crawl_log(self.conn, self.day, self.log, start=self.written)
            self.conn.commit()
            self.written += len(self.log)
            self.log = []

    def close_spider(self, spider=None):
        self.flush()
        self.conn.close()
