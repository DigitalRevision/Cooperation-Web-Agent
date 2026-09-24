"""Нормализация, дедупликация, проверка источника и запись в Git-репозиторий данных.

Краулер НЕ изменяет company.json / products.json. Он пишет сырые результаты в data/crawl/<company>/<date>.jsonl
и журнал обхода в data/sources/crawl_log_<date>.json. Перенос фактов в карточку — через pull request с проверкой модератора.
"""
import json, os, re, subprocess
from datetime import date
from urllib.parse import urlparse
from scrapy.exceptions import DropItem


class NormalizePipeline:
    def process_item(self, item, spider):
        if item.get("extracted"):
            ex = item["extracted"]
            ex["phones"] = sorted({re.sub(r"[^\d+]", "", p) for p in ex["phones"]})
            ex["emails"] = sorted({e.lower().rstrip(".") for e in ex["emails"]})
        return item


class DedupPipeline:
    def __init__(self):
        self.seen = set()

    def process_item(self, item, spider):
        key = item.get("content_hash") or item["url"]
        if key in self.seen:
            raise DropItem(f"duplicate {item['url']}")
        self.seen.add(key)
        return item


class SourceValidationPipeline:
    """Официальный источник должен быть на домене из sources.yaml; ИНН сверяется с карточкой предприятия."""
    def open_spider(self, spider):
        self.data = spider.settings.get("PK_DATA_DIR")

    def process_item(self, item, spider):
        if item.get("extracted") and item["extracted"]["inn"]:
            p = os.path.join(self.data, "companies", item["company_id"], "company.json")
            if os.path.exists(p):
                inn = json.load(open(p, encoding="utf-8")).get("inn")
                item["extracted"]["inn_matches_card"] = inn in item["extracted"]["inn"] if inn else None
        item["domain"] = urlparse(item["url"]).hostname
        return item


class GitDataPipeline:
    def open_spider(self, spider):
        self.root = spider.settings.get("PK_DATA_DIR")
        self.day = date.today().isoformat()
        self.log = []

    def process_item(self, item, spider):
        d = os.path.join(self.root, "crawl", item["company_id"])
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{self.day}.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(item), ensure_ascii=False) + "\n")
        self.log.append({"url": item["url"], "status": item["fetch_status"], "note": item["source_title"], "fetched_at": self.day})
        return item

    def close_spider(self, spider):
        p = os.path.join(self.root, "sources", f"crawl_log_{self.day}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.log, f, ensure_ascii=False, indent=2)
        if spider.settings.getbool("PK_GIT_COMMIT"):
            subprocess.run(["git", "-C", self.root, "add", "crawl", "sources"], check=False)
            subprocess.run(["git", "-C", self.root, "commit", "-m", f"crawl: {self.day}, {len(self.log)} pages"], check=False)
