import scrapy


class PageItem(scrapy.Item):
    company_id = scrapy.Field()
    url = scrapy.Field()
    source_url = scrapy.Field()  # адрес из sources.yaml, с которого начат обход
    domain = scrapy.Field()
    source_type = scrapy.Field()
    source_title = scrapy.Field()
    priority = scrapy.Field()
    http_status = scrapy.Field()
    fetch_status = scrapy.Field()
    fetched_at = scrapy.Field()
    last_modified = scrapy.Field()
    content_hash = scrapy.Field()
    text = scrapy.Field()
    extracted = scrapy.Field()   # {"emails": [], "phones": [], "inn": [], "ogrn": [], "product_headings": [], "links": []}


class SiteItem(scrapy.Item):
    """Проверенный домен-кандидат в официальные сайты предприятия (sm01_ingest.site_discovery)."""
    company_id = scrapy.Field()
    domain = scrapy.Field()
    url = scrapy.Field()
    method = scrapy.Field()      # guess | email
    status = scrapy.Field()      # CONFIRMED | CANDIDATE
    evidence = scrapy.Field()


class SearchItem(scrapy.Item):
    """Итог поиска сайта предприятия (sm01_ingest.site_search): сколько доменов проверено и что найдено."""
    company_id = scrapy.Field()
    candidates = scrapy.Field()
    found = scrapy.Field()
