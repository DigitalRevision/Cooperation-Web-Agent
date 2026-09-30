"""Обход официальных сайтов предприятий: организация → поиск сайта → обход сайта → позиции продукции.

1. Организации — все предприятия каталога (sm01_catalog), кроме ликвидированных.
2. Сайт: известный (поле site, источник OFFICIAL_SITE или найденный раньше и подтверждённый); если сайта нет — поиск
   (pkcrawler/discovery.py): домены-кандидаты по названию и почте, на каждом — главная, контакты, реквизиты; сайт
   подтверждён, если там ИНН или ОГРН предприятия либо его название вместе с адресом из ЕГРЮЛ. Итог — в sm01_ingest
   (site_discovery, site_search); повторный поиск — не раньше чем через PK_DISCOVER_RECHECK_DAYS дней (30).
3. Подтверждённый сайт обходится сразу, в том же запуске.
4. Позиции продукции из страниц сайта записывает в каталог tools/crawl_products.py auto (вместе с найденными сайтами).
  scrapy crawl company_sites                          # все предприятия: известные сайты и поиск для остальных
  scrapy crawl company_sites -a discover=0            # только известные сайты, без поиска
  scrapy crawl company_sites -a discover_limit=200    # поиск сайта не больше чем для 200 предприятий за запуск
  scrapy crawl company_sites -a companies=ko,kzbi     # только перечисленные
  scrapy crawl company_sites -a targets=yaml          # прежний список crawler/sources.yaml
  scrapy crawl company_sites -a jobs=<id>,<id>        # задания повторного обхода из админ-панели (crawl_job), без поиска
Постоянный запуск (после каждого сбора из реестров и по заданиям из админ-панели) — crawler/daemon.py.

Что извлекается — только написанное на странице: e-mail, телефоны, ИНН/ОГРН, заголовок, хлебные крошки, карточки и пункты
каталога продукции, характеристики из таблиц. Решение «это продукция предприятия» принимает tools/crawl_products.py
(название должно быть на странице официального сайта) и модератор; краулер карточки каталога не меняет.
"""
import asyncio
import hashlib
import os
import re
import socket
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import scrapy
import yaml
from scrapy.exceptions import IgnoreRequest
from scrapy.http import TextResponse
from scrapy.spidermiddlewares.httperror import HttpError

from .. import discovery
from ..items import PageItem, SearchItem, SiteItem
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
# домены-кандидаты проверяются одним-двумя запросами: соединение закрывается сразу, иначе тысячи открытых соединений
# упираются в предел select() (512 сокетов на Windows)
ONE_SHOT = {"Connection": "close"}
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

    def __init__(self, targets="db", companies=None, max_pages=None, discover=None, discover_limit=None, recheck_days=None, jobs=None, *a, **kw):
        super().__init__(*a, **kw)
        self.targets_mode = targets
        self.job_ids = [x.strip() for x in jobs.split(",") if x.strip()] if jobs else None
        self.only = {x.strip() for x in companies.split(",")} if companies else None
        self._max_pages = int(max_pages) if max_pages else None
        self.discover = (discover if discover is not None else os.environ.get("PK_DISCOVER", "1")) not in ("0", "false", "no")
        self.discover_limit = int(discover_limit or os.environ.get("PK_DISCOVER_LIMIT") or 0)
        self.recheck_days = int(recheck_days or os.environ.get("PK_DISCOVER_RECHECK_DAYS") or 30)
        self.pages: dict[str, int] = {}     # предприятие → страниц в очереди
        self.seen: set[str] = set()
        self.found: dict[str, int] = {"CONFIRMED": 0, "CANDIDATE": 0, "searched": 0}

    # ---------- кого обходить ----------
    def db_targets(self):
        from pkdb import connect
        with connect("catalog") as c:
            rows = c.execute("""SELECT c.id, c.name, c.site, s.source_url, s.source_title FROM company c
                                LEFT JOIN source s ON s.company_id = c.id AND s.source_type = 'OFFICIAL_SITE'
                                WHERE c.site IS NOT NULL OR s.id IS NOT NULL ORDER BY c.id, s.pos""").fetchall()
            names = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM company")}
        by: dict[str, dict] = {}
        for r in rows:
            t = by.setdefault(r["id"], {"company_id": r["id"], "name": r["name"], "urls": []})
            for u in (r["site"], r["source_url"]):
                if u and u not in t["urls"]:
                    t["urls"].append(u)
        # сайты, найденные поиском в прошлых запусках, но ещё не записанные в карточку
        for cid, url in self.confirmed_sites().items():
            if cid not in by and cid in names:
                by[cid] = {"company_id": cid, "name": names[cid], "urls": [url]}
        for t in by.values():
            for u in t["urls"]:
                yield {"company_id": t["company_id"], "url": u, "type": "OFFICIAL_SITE", "title": f"Официальный сайт {t['name']}",
                       "priority": 1, "hosts": sorted({host(x) for x in t["urls"]})}

    def job_targets(self) -> list[dict]:
        """Задания повторного обхода (crawl_job): адрес и предприятие — указанное в задании или то, чей это сайт.
        Адрес, который ни к одному предприятию каталога не относится, отклоняется: страницу некуда записать."""
        from pkdb import connect, ingest
        known = list(self.db_targets())
        by_host = {h: t for t in known for h in t["hosts"]}
        by_company = {t["company_id"]: t for t in known}
        with connect("catalog") as c:
            names = {r["id"]: r["name"] for r in c.execute("SELECT id, name FROM company")}
        out = []
        with connect("ingest") as g:
            for j in g.execute("SELECT * FROM crawl_job WHERE id = ANY(%s) ORDER BY created_at", (self.job_ids,)).fetchall():
                cid = j["organization_id"]
                t = by_company.get(cid) if cid else by_host.get(host(j["url"]))
                if not t and cid in names:   # предприятие без известного сайта: обходим сайт из задания
                    t = {"company_id": cid, "type": "OFFICIAL_SITE", "title": f"Официальный сайт {names[cid]}", "priority": 1, "hosts": []}
                if not t:
                    ingest.crawl_job_fail(g, j["id"], "адрес не относится к сайту предприятия из каталога" if not cid else "предприятия нет в каталоге")
                    continue
                out.append({**t, "url": j["url"], "hosts": sorted(set(t["hosts"]) | {host(j["url"])})})
            g.commit()
        return out

    def yaml_targets(self):
        with open("sources.yaml", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        for s in cfg["sources"]:
            if not s.get("disabled"):
                yield {**s, "hosts": [host(s["url"])]}

    def confirmed_sites(self) -> dict[str, str]:
        from pkdb import connect
        with connect("ingest") as g:
            return {r["company_id"]: r["url"] for r in g.execute(
                "SELECT DISTINCT ON (company_id) company_id, url FROM site_discovery WHERE status = 'CONFIRMED' ORDER BY company_id, checked_at DESC")}

    def discovery_targets(self, known: set[str]) -> list[dict]:
        """Предприятия без сайта, у которых сайт не искали последние recheck_days дней (ликвидированные — нет)."""
        from pkdb import connect
        from pkdb import catalog as cat
        since = datetime.now(timezone.utc) - timedelta(days=self.recheck_days)
        with connect("ingest") as g:
            recent = {r["company_id"] for r in g.execute("SELECT company_id FROM site_search WHERE searched_at >= %s", (since,))}
        with connect("catalog") as c:
            comps, _, _ = cat.load_companies(c)
        # крупные по выручке первыми: по всей стране поиск идёт несколько суток, самые заметные предприятия нужны раньше
        revenue = lambda x: ((((x.get("registry") or {}).get("finance") or [{}])[0]).get("revenue") or 0)
        out = [x for cid, x in sorted(comps.items(), key=lambda kv: (-revenue(kv[1]), kv[0])) if cid not in known and cid not in recent
               and not x.get("site") and x.get("status_code") != "LIQUIDATED" and (not self.only or cid in self.only)]
        return out[:self.discover_limit] if self.discover_limit else out

    def start_requests(self):
        self.max_pages = self._max_pages or self.settings.getint("PK_MAX_PAGES_PER_SITE", 120)
        self.max_hops = self.settings.getint("PK_MAX_HOPS", 3)
        targets = self.yaml_targets() if self.targets_mode == "yaml" else self.job_targets() if self.job_ids else self.db_targets()
        self.known = set()
        for s in targets:
            self.known.add(s["company_id"])
            if self.only and s["company_id"] not in self.only:
                continue
            req = self.follow_req(s["url"], s, 0)
            if req:
                yield req

    async def start(self):   # Scrapy 2.13+: точка входа вместо start_requests
        for req in self.start_requests():
            yield req
        if not self.discover or self.targets_mode == "yaml" or self.job_ids:
            return
        todo = self.discovery_targets(self.known)
        self.logger.info("поиск сайтов: %d предприятий без сайта", len(todo))
        # домены-кандидаты проверяются пачками в отдельном потоке (DNS и открытый порт 443 или 80): запросы идут только к живым;
        # следующая пачка проверяется, пока паук работает с текущей
        def prepare(batch):
            cands = {c["id"]: discovery.candidate_domains(c) for c in batch}
            return cands, resolve_live(sorted({d for v in cands.values() for d, _ in v}))
        batches = [todo[i:i + 50] for i in range(0, len(todo), 50)]
        nxt = asyncio.ensure_future(asyncio.to_thread(prepare, batches[0])) if batches else None
        for k, batch in enumerate(batches):
            cands, live = await nxt
            nxt = asyncio.ensure_future(asyncio.to_thread(prepare, batches[k + 1])) if k + 1 < len(batches) else None
            for c in batch:
                alive = [(d, m, live[d]) for d, m in cands[c["id"]] if d in live]
                self.found["searched"] += 1
                if not alive:
                    if discovery.search_enabled():   # ни одного живого домена по названию — сразу поисковик
                        for x in self.site_next({"c": c, "cands": [], "i": -1}):
                            yield x
                    else:
                        yield SearchItem(company_id=c["id"], candidates=0, found=None)
                    continue
                yield self.site_check(c, alive, 0)

    # ---------- поиск сайта ----------
    def site_check(self, c, cands, i, scheme=None, searched=False):
        domain, method, open_scheme = cands[i]
        scheme = scheme or open_scheme
        state = {"c": c, "cands": cands, "i": i, "domain": domain, "method": method, "scheme": scheme, "pages": [], "queue": None,
                 "home": None, "candidate": None, "searched": searched}
        return scrapy.Request(f"{scheme}://{domain}/", callback=self.site_home, errback=self.site_home_failed, priority=-1,
                              dont_filter=True, headers=ONE_SHOT, meta={"disc": state, "dont_retry": True, "download_timeout": 20})

    def site_home(self, response):
        st = response.meta["disc"]
        if not isinstance(response, TextResponse) or discovery.denied(response.url):
            yield from self.site_next(st)
            return
        st["home"] = response.url
        st["pages"].append((response.url, page_text(response)))
        links = [(a.attrib.get("href", ""), clean(" ".join(a.css("::text").getall()))) for a in response.css("a[href]")]
        st["queue"] = discovery.contact_links(response.url, links)
        yield from self.site_decide(st)

    def site_home_failed(self, failure):
        st = failure.request.meta["disc"]
        if st["scheme"] == "https" and not failure.check(HttpError, IgnoreRequest):     # нет HTTPS — пробуем HTTP; robots.txt — нет
            yield self.site_check(st["c"], st["cands"], st["i"], scheme="http", searched=st.get("searched", False))
            return
        yield from self.site_next(st)

    def site_page(self, response):
        st = response.meta["disc"]
        if isinstance(response, TextResponse) and discovery.host(response.url) == discovery.host(st["home"]):
            st["pages"].append((response.url, page_text(response)))
        yield from self.site_decide(st)

    def site_page_failed(self, failure):
        yield from self.site_decide(failure.request.meta["disc"])

    def site_decide(self, st):
        """После каждой страницы: подтверждено — записываем и обходим сайт; иначе следующая страница или следующий домен."""
        c = st["c"]
        ev = discovery.evidence(c, st["pages"])
        if ev["status"] == "CONFIRMED":
            url = st["home"]
            self.found["CONFIRMED"] += 1
            yield SiteItem(company_id=c["id"], domain=discovery.host(url), url=url, method=st["method"], status="CONFIRMED", evidence=ev)
            yield SearchItem(company_id=c["id"], candidates=st["i"] + 1, found=url)
            src = {"company_id": c["id"], "url": url, "type": "OFFICIAL_SITE", "title": f"Официальный сайт {c['name']}", "priority": 1,
                   "hosts": [discovery.host(url)]}
            req = self.follow_req(url, src, 0)
            if req:
                yield req
            return
        if ev["status"] == "REJECTED" and ev.get("by") == "directory":
            st["queue"] = []
        if st["queue"]:
            url = st["queue"].pop(0)
            yield scrapy.Request(url, callback=self.site_page, errback=self.site_page_failed, priority=-1, dont_filter=True,
                                 headers=ONE_SHOT, meta={"disc": st, "dont_retry": True, "download_timeout": 20})
            return
        if ev["status"] == "CANDIDATE":
            self.found["CANDIDATE"] += 1
            yield SiteItem(company_id=c["id"], domain=discovery.host(st["home"]), url=st["home"], method=st["method"], status="CANDIDATE", evidence=ev)
        yield from self.site_next(st)

    def site_next(self, st):
        if st["i"] + 1 < len(st["cands"]):
            yield self.site_check(st["c"], st["cands"], st["i"] + 1, searched=st.get("searched", False))
        elif discovery.search_enabled() and not st.get("searched"):
            # домены по названию не подтвердились — спрашиваем поисковик (платно, поэтому только теперь)
            url, headers, body = discovery.search_request(st["c"])
            yield scrapy.Request(url, method="POST", headers=headers, body=body, callback=self.search_results, errback=self.search_failed,
                                 dont_filter=True, priority=-1, meta={"disc": st, "dont_obey_robotstxt": True, "download_slot": "search-api",
                                                                      "download_timeout": 30})
        else:
            yield SearchItem(company_id=st["c"]["id"], candidates=len(st["cands"]), found=None)

    def search_results(self, response):
        st = response.meta["disc"]
        try:
            found = discovery.search_domains(response.body, {d for d, _, _ in st["cands"]})
        except (ValueError, KeyError, SyntaxError) as e:
            self.logger.warning("поисковик вернул непонятный ответ для %s: %s", st["c"]["id"], e)
            found = []
        cands = st["cands"] + [(d, "search", "https") for d in found]
        st.update(searched=True)
        if len(cands) > len(st["cands"]):
            yield self.site_check(st["c"], cands, len(st["cands"]), searched=True)
        else:
            yield SearchItem(company_id=st["c"]["id"], candidates=len(st["cands"]), found=None)

    def search_failed(self, failure):
        st = failure.request.meta["disc"]
        self.logger.warning("поисковик недоступен для %s: %s", st["c"]["id"], failure.value)
        yield SearchItem(company_id=st["c"]["id"], candidates=len(st["cands"]), found=None)

    def closed(self, reason):
        if self.found["searched"]:
            self.logger.info("поиск сайтов: проверено предприятий %d, подтверждено сайтов %d, на решение модератора %d",
                             self.found["searched"], self.found["CONFIRMED"], self.found["CANDIDATE"])

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
        text = page_text(response)
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


def page_text(response) -> str:
    """Текст страницы без скриптов и стилей, включая текст прямо внутри <body>."""
    return " ".join(t.strip() for t in response.xpath("//body//text()[not(ancestor::script or ancestor::style or ancestor::noscript)]").getall()
                    if t.strip())


def resolve_live(domains: list[str]) -> dict[str, str]:
    """Живые домены и схема: есть адрес в DNS и принимает соединения порт 443 (https) или 80 (http).
    Несуществующие домены и выключенные серверы отсеиваются без HTTP-запросов и повторов."""
    def probe(d):
        try:
            socket.getaddrinfo(d, 443, proto=socket.IPPROTO_TCP)
        except (OSError, UnicodeError):
            return None
        for port, scheme in ((443, "https"), (80, "http")):
            try:
                socket.create_connection((d, port), timeout=5).close()
                return scheme
            except OSError:
                continue
        return None
    with ThreadPoolExecutor(32) as ex:
        return {d: s for d, s in zip(domains, ex.map(probe, domains)) if s}
