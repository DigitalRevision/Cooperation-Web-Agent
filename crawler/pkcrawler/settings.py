"""Бережный обход: robots.txt, низкая частота, повтор только временных ошибок."""
import logging
import os
from pathlib import Path

# поиск сайтов проверяет тысячи чужих доменов: сертификаты хостингов и недоступные robots.txt — обычное дело, не ошибки обхода
logging.getLogger("scrapy.core.downloader.tls").setLevel(logging.ERROR)
logging.getLogger("scrapy.downloadermiddlewares.robotstxt").setLevel(logging.CRITICAL)
BOT_NAME = "pkcrawler"
SPIDER_MODULES = ["pkcrawler.spiders"]
USER_AGENT = "PromKoopBot/0.2 (+https://sm01.xroyse.ru/)"  # оператор обхода — платформа «Промышленная кооперация»
ROBOTSTXT_OBEY = True
# к одному сайту — один запрос раз в 3 секунды; разных сайтов одновременно — до 48 (поиск сайтов проверяет тысячи доменов,
# запросы, ждущие паузы к своему сайту, тоже занимают место в этом лимите)
CONCURRENT_REQUESTS = int(os.environ.get("PK_CRAWL_CONCURRENCY", "48"))   # всего по всем сайтам; на один сайт — по-прежнему 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 3
# широкий обход (сотни сайтов): следующий запрос берётся для сайта, который сейчас свободен, — иначе страницы одного сайта,
# ждущие своей паузы, занимают все места, а остальные сайты и поиск сайтов простаивают
SCHEDULER_PRIORITY_QUEUE = "scrapy.pqueues.DownloaderAwarePriorityQueue"
# Яндекс Search API (если задан ключ): до 4 запросов одновременно, не чаще 4 в секунду
DOWNLOAD_SLOTS = {"search-api": {"concurrency": 4, "delay": 0.25}}
COOKIES_ENABLED = False
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 3
AUTOTHROTTLE_MAX_DELAY = 30
AUTOTHROTTLE_TARGET_CONCURRENCY = 0.5
RETRY_ENABLED = True
RETRY_TIMES = 2
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408, 429]   # 403/404 не повторяем — фиксируем как ошибку источника
# глубину ограничивает сам паук: PK_MAX_HOPS переходов от главной и PK_MAX_PAGES_PER_SITE страниц на предприятие.
# Общий DEPTH_LIMIT выключен: поиск сайта проверяет домены цепочкой запросов, и её длина — не глубина обхода сайта
DEPTH_LIMIT = 0
# глубина по разделам каталога (главная → каталог → раздел → позиция) и предел страниц на одно предприятие
PK_MAX_HOPS = 3
PK_MAX_PAGES_PER_SITE = 120
DOWNLOAD_TIMEOUT = 30
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 86400
# Trash — кеш и служебные файлы проекта, можно очищать целиком (clean.cmd)
HTTPCACHE_DIR = str(Path(__file__).resolve().parents[2] / "Trash" / "scrapy")
LOG_LEVEL = "INFO"
ITEM_PIPELINES = {
    "pkcrawler.pipelines.NormalizePipeline": 100,
    "pkcrawler.pipelines.DedupPipeline": 200,
    "pkcrawler.pipelines.SourceValidationPipeline": 300,
    "pkcrawler.pipelines.PostgresPipeline": 900,
}
# Результаты пишутся в базу sm01_ingest; адрес — PK_DB_URL_INGEST или PK_PG_URL (см. pkdb/db.py)
# Playwright включать только для сайтов, где контент рендерится JavaScript (scrapy-playwright), по списку в sources.yaml
