"""Обход официальных сайтов предприятий.

Кого обходить: по умолчанию — все предприятия каталога (sm01_catalog), у которых известен официальный сайт (поле site или
источник OFFICIAL_SITE). Список пополняется сам: сайт появляется у карточки — предприятие попадает в следующий обход.
  scrapy crawl company_sites                          # все предприятия с сайтом
  scrapy crawl company_sites -a companies=ko,kzbi     # только перечисленные
  scrapy crawl company_sites -a targets=yaml          # прежний список crawler/sources.yaml

Что извлекается — только написанное на странице: e-mail, телефоны, ИНН/ОГРН, заголовок, хлебные крошки, карточки и пункты
каталога продукции, характеристики из таблиц. Решение «это продукция предприятия» принимает tools/crawl_products.py
(название должно быть на странице официального сайта) и модератор; краулер карточки каталога не меняет.
"""
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import scrapy
import yaml
from scrapy.http import TextResponse
from scrapy.spidermiddlewares.httperror import HttpError

from ..items import PageItem
from ..pipelines import host

_root = Path(__file__).resolve().parents[3]
if (_root / "pkdb").is_dir() and str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:\+7|8)[\s(-]*\d{3,5}[\s)-]*\d{1,3}[\s-]?\d{2}[\s-]?\d{2}")
INN = re.compile(r"ИНН[:\s]*(\d{10}|\d{12})")
OGRN = re.compile(r"ОГРН[:\s]*(\d{13}|\d{15})")
PRODUCT_HINTS = re.compile(r"продукц|каталог|изделия|услуг|оборудован|товар|производим|номенклатур|ассортимент", re.I)
# адреса разделов обычно латиницей: /produkciya/, /catalog/, /uslugi/
URL_HINTS = re.compile(r"produk|product|katalog|catalog|izdeli|uslug|servic|oborud|equipment|goods|tovar|nomenklat|assortiment|prod/", re.I)
# не ходим: файлы, служебные и повторяющиеся страницы (сортировки, фильтры, корзина, поиск, вход)
SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|webp|svg|docx?|xlsx?|pptx?|zip|rar|7z|mp4|avi|mov|dwg|exe)$", re.I)
SKIP_URL = re.compile(r"(/basket|/cart|/personal|/auth|/login|/search|/bitrix/|/download/|/upload/|sort=|order=|filter|set_filter|print=|/rss|mailto:|tel:|javascript:)", re.I)
# служебные разделы сайта: туда не ходим, это не продукция
NOISE_PATH = re.compile(r"/(news|novosti|press|article|stati|blog|event|sobyti|vakans|vacanc|career|kariera|kontakt|contact|smi|media|foto|photo|"
                        r"video|gallery|galereya|otzyv|review|dokument|document|licenz|sertifik|certific|history|istoriya|zakupk|tender|"
                        r"purchase|expert-form|feedback|politika|privacy|sitemap|en)(/|$)", re.I)
# контейнеры, внутри которых ссылки — навигация сайта, а не каталог (кроме меню каталога)
NOISE_CLASS = re.compile(r"(footer|header|social|share|news|banner|slider|breadcrumb|pagination|pager|cookie|modal|popup|search|basket|cart|lang)", re.I)
CARD_CLASS = re.compile(r"(product|catalog|goods|tovar|item|card|prod|model|series|izdel)", re.I)


def canon(url: str) -> str:
    """Адрес без фрагмента и завершающей косой черты: одна страница — один адрес."""
    u = urlparse(url)
    path = re.sub(r"/index\.(php|html?)$", "/", u.path) or "/"
    return urlunparse((u.scheme, u.netloc.lower(), path.rstrip("/") or "/", "", u.query, ""))


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


class CompanySitesSpider(scrapy.Spider):
    name = "company_sites"

    def __init__(self, targets="db", companies=None, max_pages=None, *a, **kw):
        super().__init__(*a, **kw)
        self.targets_mode = targets
        self.only = {x.strip() for x in companies.split(",")} if companies else None
        self._max_pages = int(max_pages) if max_pages else None
        self.pages: dict[str, int] = {}     # предприятие → страниц в очереди
        self.seen: set[str] = set()

    # ---------- кого обходить ----------
    def db_targets(self):
        from pkdb import connect
        with connect("catalog") as c:
            rows = c.execute("""SELECT c.id, c.name, c.site, s.source_url, s.source_title FROM company c
                                LEFT JOIN source s ON s.company_id = c.id AND s.source_type = 'OFFICIAL_SITE'
                                WHERE c.site IS NOT NULL OR s.id IS NOT NULL ORDER BY c.id, s.pos""").fetchall()
        by: dict[str, dict] = {}
        for r in rows:
            t = by.setdefault(r["id"], {"company_id": r["id"], "name": r["name"], "urls": []})
            for u in (r["site"], r["source_url"]):
                if u and u not in t["urls"]:
                    t["urls"].append(u)
        for t in by.values():
            for u in t["urls"]:
                yield {"company_id": t["company_id"], "url": u, "type": "OFFICIAL_SITE", "title": f"Официальный сайт {t['name']}",
                       "priority": 1, "hosts": sorted({host(x) for x in t["urls"]})}

    def yaml_targets(self):
        with open("sources.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        for s in cfg["sources"]:
            if not s.get("disabled"):
                yield {**s, "hosts": [host(s["url"])]}

    def start_requests(self):
        self.max_pages = self._max_pages or self.settings.getint("PK_MAX_PAGES_PER_SITE", 120)
        self.max_hops = self.settings.getint("PK_MAX_HOPS", 3)
        targets = self.yaml_targets() if self.targets_mode == "yaml" else self.db_targets()
        for s in targets:
            if self.only and s["company_id"] not in self.only:
                continue
            req = self.follow_req(s["url"], s, 0)
            if req:
                yield req

    async def start(self):   # Scrapy 2.13+: точка входа вместо start_requests
        for req in self.start_requests():
            yield req

    def follow_req(self, url, src, hop, priority=0):
        c = canon(url)
        if c in self.seen or self.pages.get(src["company_id"], 0) >= self.max_pages:
            return None
        self.seen.add(c)
        self.pages[src["company_id"]] = self.pages.get(src["company_id"], 0) + 1
        return scrapy.Request(url, callback=self.parse, errback=self.failed, priority=priority, meta={"src": src, "hop": hop})

    # ---------- разбор страницы ----------
    def parse(self, response):
        src, hop = response.meta["src"], response.meta["hop"]
        if not isinstance(response, TextResponse):   # файл (прайс, чертёж, каталог), а не страница
            return
        text = " ".join(t.strip() for t in response.css("body *:not(script):not(style):not(noscript)::text").getall() if t.strip())
        h1 = clean(" ".join(response.css("h1 ::text").getall()))
        crumbs = [clean(x) for x in response.xpath('//*[contains(@class,"breadcrumb") or @aria-label="breadcrumb" or @itemtype="https://schema.org/BreadcrumbList"]//a//text() | '
                                                   '//*[contains(@class,"breadcrumb")]//span[not(ancestor::a)]//text()').getall() if clean(x)]
        headings = [clean(h) for h in response.css("nav a::text, h1::text, h2::text, h3::text").getall() if PRODUCT_HINTS.search(h or "") or len(clean(h)) > 3][:80]
        cards, catalog_menu = self.cards(response)
        # заголовки разделов страницы: на страницах услуг и продукции позиции часто оформлены заголовками, а не ссылками
        sections = [clean(" ".join(h.css("::text").getall())) for h in response.xpath("//main//h2 | //main//h3 | //article//h2 | //article//h3 | //*[contains(@class,'content')]//h2 | //*[contains(@class,'content')]//h3")]
        sections = [x for x in dict.fromkeys(sections) if 3 <= len(x) <= 160][:60]
        specs = []
        for tr in response.css("table tr")[:80]:
            cells = [clean(" ".join(td.css("::text").getall())) for td in tr.css("td, th")]
            if len(cells) == 2 and 1 < len(cells[0]) < 80 and cells[1] and len(cells[1]) < 200:
                specs.append(cells)
        yield PageItem(
            company_id=src["company_id"], url=response.url, source_url=src["url"], source_type=src["type"], source_title=src["title"],
            priority=src["priority"], http_status=response.status, fetch_status="OK", fetched_at=datetime.now(timezone.utc).isoformat(),
            last_modified=response.headers.get("Last-Modified", b"").decode(errors="ignore") or None,
            content_hash=hashlib.sha256(text.encode()).hexdigest(), text=text[:200000],
            extracted={"emails": sorted(set(EMAIL.findall(text))), "phones": sorted(set(PHONE.findall(text))),
                       "inn": sorted(set(INN.findall(text))), "ogrn": sorted(set(OGRN.findall(text))),
                       "title": clean(response.css("title::text").get()), "h1": h1, "breadcrumbs": crumbs, "hop": hop,
                       "product_headings": headings, "sections": sections, "cards": cards, "catalog_menu": catalog_menu, "specs": specs[:40],
                       "links": response.css("a::attr(href)").getall()[:300]})
        if hop >= self.max_hops:
            return
        # по разделам продукции идём в пределах домена предприятия; страницы внутри раздела каталога — тоже
        here = urlparse(response.url).path
        in_catalog = bool(URL_HINTS.search(here))
        catalog_links = {canon(c["url"]) for c in cards + catalog_menu}
        for a in response.css("a[href]"):
            href = a.attrib.get("href", "")
            if not href or SKIP_URL.search(href):
                continue
            url = response.urljoin(href)
            p = urlparse(url)
            if p.scheme not in ("http", "https") or host(url) not in src["hosts"] or SKIP_EXT.search(p.path):
                continue
            if "PAGEN" not in (p.query or "") and p.query:
                continue
            if NOISE_PATH.search(p.path):
                continue
            label = clean(" ".join(a.css("::text").getall()))
            hinted = URL_HINTS.search(p.path) or PRODUCT_HINTS.search(label)
            deeper = in_catalog and p.path.startswith(here.rstrip("/") + "/")
            listed = canon(url) in catalog_links   # пункт меню каталога или карточка позиции
            # сайт предприятия обходится целиком (кроме служебных разделов) в пределах PK_MAX_PAGES_PER_SITE:
            # разделы каталога и пункты меню — первыми
            req = self.follow_req(url, src, hop + 1, priority=10 if deeper else 8 if listed else 5 if hinted else 1)
            if req:
                yield req

    def cards(self, response):
        """Карточки и пункты каталога: ссылки внутри блоков с классами product/catalog/item/card…, кроме навигации сайта."""
        cards, menu, seen = [], [], set()
        for el in response.xpath("//*[@class]"):
            cls = el.attrib.get("class", "")
            if not CARD_CLASS.search(cls) or NOISE_CLASS.search(cls):
                continue
            if el.xpath("ancestor::*[self::footer or self::header]") or any(NOISE_CLASS.search(x) for x in el.xpath("ancestor::*/@class").getall()):
                continue
            is_menu = bool(re.search(r"menu|nav|sidebar|aside|left", cls, re.I)) or el.xpath("boolean(ancestor::nav or ancestor::aside)").get() == "1"
            for a in el.css("a[href]")[:60]:
                name = clean(" ".join(a.css("::text").getall())) or clean(a.attrib.get("title"))
                if not name:
                    name = clean(" ".join(el.css("h2 ::text, h3 ::text, h4 ::text, .name ::text, .title ::text").getall()))
                url = response.urljoin(a.attrib["href"])
                key = (name.lower(), canon(url))
                if not (3 <= len(name) <= 160) or key in seen or SKIP_URL.search(url):
                    continue
                seen.add(key)
                (menu if is_menu else cards).append({"name": name, "url": url, "cls": cls[:80]})
                if len(cards) + len(menu) >= 300:
                    return cards, menu
        return cards, menu

    def failed(self, failure):
        req = failure.request
        status = failure.value.response.status if failure.check(HttpError) else None
        src = req.meta["src"]
        yield PageItem(company_id=src["company_id"], url=req.url, source_url=src["url"], source_type=src["type"], source_title=src["title"],
                       priority=src["priority"], http_status=status, fetch_status=f"HTTP_{status}" if status else type(failure.value).__name__.upper(),
                       fetched_at=datetime.now(timezone.utc).isoformat(), text=None, extracted=None, content_hash=None)
