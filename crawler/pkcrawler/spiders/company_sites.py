"""Обход официальных сайтов предприятий из crawler/sources.yaml.

Извлекается только то, что написано на странице: e-mail, телефоны, ИНН/ОГРН, заголовки разделов продукции, ссылки.
Решение «это продукция предприятия» принимает модератор при слиянии в data/ (pull request), а не краулер.
"""
import hashlib, re
from datetime import datetime, timezone
import scrapy, yaml
from scrapy.spidermiddlewares.httperror import HttpError
from ..items import PageItem

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:\+7|8)[\s(-]*\d{3,5}[\s)-]*\d{1,3}[\s-]?\d{2}[\s-]?\d{2}")
INN = re.compile(r"ИНН[:\s]*(\d{10}|\d{12})")
OGRN = re.compile(r"ОГРН[:\s]*(\d{13}|\d{15})")
PRODUCT_HINTS = re.compile(r"продукц|каталог|изделия|услуг|оборудован", re.I)


class CompanySitesSpider(scrapy.Spider):
    name = "company_sites"

    def start_requests(self):
        with open("sources.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        for s in cfg["sources"]:
            if s.get("disabled"):
                continue
            yield scrapy.Request(s["url"], callback=self.parse, errback=self.failed, meta={"src": s, "depth_label": 0})

    def parse(self, response):
        src = response.meta["src"]
        text = " ".join(t.strip() for t in response.css("body *:not(script):not(style)::text").getall() if t.strip())
        headings = [h.strip() for h in response.css("nav a::text, h1::text, h2::text, h3::text").getall() if PRODUCT_HINTS.search(h or "") or len(h.strip()) > 3][:80]
        yield PageItem(
            company_id=src["company_id"], url=response.url, source_type=src["type"], source_title=src["title"], priority=src["priority"],
            http_status=response.status, fetch_status="OK", fetched_at=datetime.now(timezone.utc).isoformat(),
            last_modified=response.headers.get("Last-Modified", b"").decode() or None,
            content_hash=hashlib.sha256(text.encode()).hexdigest(), text=text[:200000],
            extracted={"emails": sorted(set(EMAIL.findall(text))), "phones": sorted(set(PHONE.findall(text))),
                       "inn": sorted(set(INN.findall(text))), "ogrn": sorted(set(OGRN.findall(text))),
                       "product_headings": headings, "links": response.css("a::attr(href)").getall()[:300]})
        for href in response.css("a::attr(href)").getall():
            if PRODUCT_HINTS.search(href) and response.meta["depth_label"] < 1:
                yield response.follow(href, callback=self.parse, errback=self.failed, meta={"src": src, "depth_label": 1})

    def failed(self, failure):
        req = failure.request
        status = failure.value.response.status if failure.check(HttpError) else None
        yield PageItem(company_id=req.meta["src"]["company_id"], url=req.url, source_type=req.meta["src"]["type"],
                       source_title=req.meta["src"]["title"], priority=req.meta["src"]["priority"], http_status=status,
                       fetch_status=f"HTTP_{status}" if status else type(failure.value).__name__.upper(),
                       fetched_at=datetime.now(timezone.utc).isoformat(), text=None, extracted=None, content_hash=None)
