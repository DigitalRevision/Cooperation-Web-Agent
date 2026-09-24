"""Бережный обход: robots.txt, низкая частота, повтор только временных ошибок."""
BOT_NAME = "pkcrawler"
SPIDER_MODULES = ["pkcrawler.spiders"]
USER_AGENT = "PromKoopBot/0.1 (+https://example.org/bot; data@example.org)"  # заменить на контакты оператора платформы
ROBOTSTXT_OBEY = True
CONCURRENT_REQUESTS = 4
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 3
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 3
AUTOTHROTTLE_MAX_DELAY = 30
AUTOTHROTTLE_TARGET_CONCURRENCY = 0.5
RETRY_ENABLED = True
RETRY_TIMES = 2
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408, 429]   # 403/404 не повторяем — фиксируем как ошибку источника
DEPTH_LIMIT = 2
DOWNLOAD_TIMEOUT = 30
HTTPCACHE_ENABLED = True
HTTPCACHE_EXPIRATION_SECS = 86400
LOG_LEVEL = "INFO"
ITEM_PIPELINES = {
    "pkcrawler.pipelines.NormalizePipeline": 100,
    "pkcrawler.pipelines.DedupPipeline": 200,
    "pkcrawler.pipelines.SourceValidationPipeline": 300,
    "pkcrawler.pipelines.GitDataPipeline": 900,
}
PK_DATA_DIR = "../data"
# Коммит результатов в Git только по явному запросу: scrapy crawl company_sites -s PK_GIT_COMMIT=1
PK_GIT_COMMIT = False
# Playwright включать только для сайтов, где контент рендерится JavaScript (scrapy-playwright), по списку в sources.yaml
