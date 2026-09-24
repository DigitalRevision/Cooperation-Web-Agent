import scrapy


class PageItem(scrapy.Item):
    company_id = scrapy.Field()
    url = scrapy.Field()
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
