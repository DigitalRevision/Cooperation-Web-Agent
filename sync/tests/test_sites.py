"""Поиск официальных сайтов краулером: домены-кандидаты, подтверждение по ИНН, ОГРН, названию и адресу, запись в каталог."""
import importlib.util
import sys
from pathlib import Path

from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "crawler"))
from pkcrawler import discovery  # noqa: E402

C = {"id": "donkabel", "short": "Донкабель", "name": "ООО «Донкабель»", "legal_name": 'ОБЩЕСТВО С ОГРАНИЧЕННОЙ ОТВЕТСТВЕННОСТЬЮ "ДОНКАБЕЛЬ"',
     "inn": "6128008660", "ogrn": "1026101691460", "region": "61", "city": "Ростов-на-Дону",
     "address": "344002, Ростовская обл., г. Ростов-на-Дону, ул. Большая Садовая, д. 15А, офис 3"}


def test_candidate_domains_from_name_email_and_abbreviation():
    doms = [d for d, _ in discovery.candidate_domains(C)]
    assert doms[0] == "donkabel.ru" and "donkabel61.ru" in doms and "donkabel.com" in doms
    assert "xn--80achgwjjh6k.xn--p1ai" in doms                                          # донкабель.рф
    assert [d for d, _ in discovery.candidate_domains({"short": "Станикс", "name": "ООО «Станикс»"})][:2] == ["staniks.ru", "stanix.ru"]
    szpu = discovery.candidate_domains({"short": "Сзпу", "name": "АО «Сзпу»", "legal_name": 'АКЦИОНЕРНОЕ ОБЩЕСТВО "САЛЬСКИЙ ЗАВОД ПРЕССОВЫХ УЗЛОВ"'})
    assert szpu[0] == ("szpu.ru", "guess") and ("salskiy-zavod-pressovyh-uzlov.ru", "guess") in szpu
    mail = discovery.candidate_domains({**C, "emails": [{"value": "info@dk-cable.ru"}, {"value": "dk@mail.ru"}]})
    assert mail[0] == ("dk-cable.ru", "email") and all(d != "mail.ru" for d, _ in mail)   # бесплатная почта — не сайт
    assert len(discovery.candidate_domains(C)) <= discovery.MAX_DOMAINS


def test_address_parts_from_egrul_formats():
    ap = lambda a: discovery.address_parts({"address": a})
    assert ap("394033, Воронежская область, Г Воронеж, Ул Землячки, д. 17, офис 1") == ("земляч", "17")
    assert ap("400005, Волгоградская обл, г Волгоград, пр-кт им. В.И. Ленина, д. 56") == ("ленина", "56")
    assert ap("413100, Саратовская обл, г Энгельс, пр-кт Строителей, зд. 7Б") == ("строит", "7")
    assert ap("346780, Ростовская обл., г. Азов, ул. Мира, д.1А") == ("мира", "1")
    assert ap("Ростовская обл., г. Шахты") is None


def test_site_confirmed_only_by_what_is_written_on_it():
    ok = discovery.evidence(C, [("https://donkabel.ru/", "Главная"), ("https://donkabel.ru/contacts/", "ИНН 6128 008 660, КПП 612801001")])
    assert ok == {"status": "CONFIRMED", "by": "inn", "page": "https://donkabel.ru/contacts/"}
    assert discovery.evidence(C, [("u", "ОГРН 1026101691460")])["by"] == "ogrn"
    assert discovery.evidence(C, [("u", "Счёт 461280086601234")])["status"] == "REJECTED"                   # ИНН внутри другого числа — нет
    addr = discovery.evidence(C, [("u", "ООО «Донкабель», г. Ростов-на-Дону, ул. Б. Садовая, 15а")])
    assert addr["status"] == "CONFIRMED" and addr["by"] == "name+address"
    # одноимённых фирм много: название и город — только на решение модератора, без города — отказ
    assert discovery.evidence(C, [("u", "Донкабель — кабельный завод, Ростов-на-Дону, ул. Мира, 1")])["status"] == "CANDIDATE"
    assert discovery.evidence(C, [("u", "Донкабель — кабельный завод")])["status"] == "REJECTED"
    many = " ".join(f"ИНН 61000000{i:02d}" for i in range(5)) + " ИНН 6128008660"
    assert discovery.evidence(C, [("u", many)]) == {"status": "REJECTED", "by": "directory", "inns": 6}      # справочник организаций
    assert discovery.denied("https://www.rusprofile.ru/id/123") and discovery.denied("http://parking.reg.ru/") and not discovery.denied("https://donkabel.ru/")


def spider():
    from pkcrawler.spiders.company_sites import CompanySitesSpider
    sp = CompanySitesSpider(discover="1")
    sp.max_pages, sp.max_hops = 5, 2
    return sp


def html(url, body, request):
    from scrapy.http import HtmlResponse
    return HtmlResponse(url=url, body=f"<html><body>{body}</body></html>".encode(), encoding="utf-8", request=request)


def test_spider_checks_contacts_confirms_site_and_starts_crawl():
    from scrapy import Request
    from pkcrawler.items import SearchItem, SiteItem
    sp = spider()
    req = sp.site_check(C, [("donkabel.ru", "guess", "https")], 0)
    out = list(sp.site_home(html("https://donkabel.ru/", '<h1>Донкабель</h1><a href="/kontakty/">Контакты</a><a href="/catalog/">Каталог</a>', req)))
    assert [r.url for r in out] == ["https://donkabel.ru/kontakty/"]                    # ИНН на главной нет — идём в контакты
    res = list(sp.site_page(html(out[0].url, "ООО «Донкабель», ИНН 6128008660", out[0])))
    site = next(x for x in res if isinstance(x, SiteItem))
    assert site["status"] == "CONFIRMED" and site["evidence"]["by"] == "inn" and site["domain"] == "donkabel.ru"
    assert next(x for x in res if isinstance(x, SearchItem))["found"] == "https://donkabel.ru/"
    crawl = [x for x in res if isinstance(x, Request)]
    assert [r.url for r in crawl] == ["https://donkabel.ru/"] and crawl[0].meta["src"]["type"] == "OFFICIAL_SITE"


def test_spider_goes_to_next_domain_and_records_search_without_site():
    from pkcrawler.items import SearchItem, SiteItem
    sp = spider()
    cands = [("donkabel.ru", "guess", "https"), ("donkabel.com", "guess", "http")]
    req = sp.site_check(C, cands, 0)
    out = list(sp.site_home(html("https://www.rusprofile.ru/id/1", "ИНН 6128008660", req)))   # перенаправление на агрегатор
    assert [r.url for r in out] == ["http://donkabel.com/"]
    out = list(sp.site_home(html("http://donkabel.com/", "Кабель оптом. Донкабель, Ростов-на-Дону", out[0])))
    while out and not isinstance(out[-1], SearchItem):                                          # контакты и реквизиты без ИНН
        out = list(sp.site_page(html(out[0].url, "Телефон отдела продаж", out[0])))
    assert any(isinstance(x, SiteItem) and x["status"] == "CANDIDATE" for x in out)            # название и город: решает модератор
    assert out[-1]["found"] is None and out[-1]["candidates"] == 2


def load_tool():
    spec = importlib.util.spec_from_file_location("crawl_products", ROOT / "tools" / "crawl_products.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def crawl_item(cid, url, h1, hop, cards=(), menu=(), text="", specs=()):
    return {"company_id": cid, "url": url, "source_url": "https://test-zavod.ru/", "source_type": "OFFICIAL_SITE", "fetch_status": "OK",
            "text": text or h1, "extracted": {"h1": h1, "hop": hop, "breadcrumbs": [], "sections": [], "specs": [list(x) for x in specs],
                                             "cards": [{"name": n, "url": u, "cls": "product-card"} for n, u in cards],
                                             "catalog_menu": [{"name": n, "url": u, "cls": "catalog-menu"} for n, u in menu]}}


BASE = "https://test-zavod.ru"


def seed_crawl(cid):
    """Результат обхода: сайт подтверждён по ИНН, на нём раздел каталога с двумя позициями и страница «Структура»."""
    from pkdb import connect
    items = [crawl_item(cid, f"{BASE}/", "Тест-Завод", 0, menu=[("Краны мостовые", f"{BASE}/catalog/krany/")]),
             crawl_item(cid, f"{BASE}/catalog/krany/", "Краны мостовые", 1,
                        cards=[("Кран мостовой однобалочный", f"{BASE}/catalog/krany/odnobalochnyy/"), ("Кран мостовой двухбалочный", f"{BASE}/catalog/krany/dvuhbalochnyy/")]),
             crawl_item(cid, f"{BASE}/catalog/krany/odnobalochnyy/", "Кран мостовой однобалочный", 2, specs=[("Грузоподъёмность", "до 12,5 т")]),
             crawl_item(cid, f"{BASE}/catalog/krany/dvuhbalochnyy/", "Кран мостовой двухбалочный", 2),
             crawl_item(cid, f"{BASE}/o-nas/struktura/", "Структура", 1)]
    with connect("ingest") as g:
        g.execute("INSERT INTO site_discovery (company_id, domain, url, method, status, evidence) VALUES (%s, 'test-zavod.ru', %s, 'guess', 'CONFIRMED', %s)",
                  (cid, f"{BASE}/", Jsonb({"by": "inn", "page": f"{BASE}/kontakty/"})))
        for it in items:
            g.execute("INSERT INTO crawl_page (company_id, url, fetch_status, content_hash, item) VALUES (%s, %s, 'OK', %s, %s)",
                      (cid, it["url"], it["url"], Jsonb(it)))
        g.commit()


def clear_crawl(cid):
    from pkdb import connect
    with connect("ingest") as g:
        g.execute("DELETE FROM site_discovery WHERE company_id = %s", (cid,))
        g.execute("DELETE FROM crawl_page WHERE company_id = %s", (cid,))
        g.commit()


def company_without_site():
    from sync.store import Store
    st = Store()
    return next(k for k, c in sorted(st.companies.items()) if not c.get("site") and c.get("inn") and c.get("status_code") != "LIQUIDATED")


def test_auto_writes_found_site_and_its_products(repo):
    from sync.store import Store
    tool = load_tool()
    cid = company_without_site()
    seed_crawl(cid)
    try:
        tool.main(["auto", "--companies", cid])
        st2 = Store()
        c = st2.companies[cid]
        assert c["site"] == f"{BASE}/" and any(h["field"] == "Официальный сайт" and h["new"] == f"{BASE}/" for h in c["history"])
        src = next(s for s in st2.sources[cid] if s["id"] == f"{cid}-site")
        assert src["source_type"] == "OFFICIAL_SITE" and "ИНН предприятия на странице" in src["note"]
        web = {p["name"]: p for p in st2.products[cid] if p["source_id"].startswith(f"{cid}-web-")}
        assert set(web) == {"Кран мостовой однобалочный", "Кран мостовой двухбалочный"}                  # «Структура» — не продукция
        assert web["Кран мостовой однобалочный"]["params"] == [{"name": "Грузоподъёмность", "value": "до 12,5 т"}]
        tool.main(["auto", "--companies", cid])                                                           # повторный запуск ничего не дублирует
        assert len([p for p in Store().products[cid] if p["source_id"].startswith(f"{cid}-web-")]) == 2
    finally:
        clear_crawl(cid)


def test_daily_sync_applies_crawler_results_once(repo):
    from sync import run
    cid = company_without_site()
    seed_crawl(cid)
    try:
        args = ["--no-discover", "--only-new", "--no-opendata", "--delay", "0"]
        doc = run.run(run.parse_args(args))
        assert doc["stats"]["sites_added"] == 1 and doc["stats"]["products_from_sites"] == 2
        assert {(ch["company_id"], ch["field"]) for ch in doc["changes"]} >= {(cid, "Официальный сайт"), (cid, "Продукция (официальный сайт)")}
        doc = run.run(run.parse_args(args))                               # страницы уже разобраны: следующий сбор их не трогает
        assert doc["stats"]["sites_added"] == 0 and doc["stats"]["products_from_sites"] == 0
    finally:
        clear_crawl(cid)


YANDEX_XML = """<?xml version="1.0" encoding="utf-8"?><yandexsearch version="1.0"><response><results><grouping>
<group><doc><url>https://www.rusprofile.ru/id/6128008660</url><domain>www.rusprofile.ru</domain><title>Донкабель</title></doc></group>
<group><doc><url>https://donkabel-rnd.ru/</url><domain>donkabel-rnd.ru</domain><title>Донкабель — кабельный завод</title></doc></group>
<group><doc><url>https://donkabel.ru/contacts/</url><domain>donkabel.ru</domain><title>Контакты</title></doc></group>
</grouping></results></response></yandexsearch>"""


def test_search_api_request_and_results(monkeypatch):
    import base64
    import json
    monkeypatch.setenv("PK_YANDEX_SEARCH_KEY", "key-1")
    monkeypatch.setenv("PK_YANDEX_FOLDER_ID", "folder-1")
    assert discovery.search_enabled()
    url, headers, body = discovery.search_request(C)
    q = json.loads(body)
    assert url == "https://searchapi.api.cloud.yandex.net/v2/web/search" and headers["Authorization"] == "Api-Key key-1"
    assert q["query"]["queryText"] == "донкабель Ростов-на-Дону официальный сайт" and q["folderId"] == "folder-1" and q["responseFormat"] == "FORMAT_XML"
    payload = json.dumps({"rawData": base64.b64encode(YANDEX_XML.encode()).decode()})
    assert discovery.search_domains(payload, {"donkabel.ru"}) == ["donkabel-rnd.ru"]       # справочник и проверенный домен — нет


def test_spider_asks_search_engine_when_name_domains_fail(monkeypatch):
    import base64
    import json
    from scrapy.http import TextResponse
    monkeypatch.setenv("PK_YANDEX_SEARCH_KEY", "key-1")
    monkeypatch.setenv("PK_YANDEX_FOLDER_ID", "folder-1")
    sp = spider()
    req = sp.site_check(C, [("donkabel.ru", "guess", "https")], 0)
    out = list(sp.site_home(html("https://donkabel.ru/", "Продаётся домен", req)))          # чужой сайт без названия
    while out and out[0].meta.get("disc") and out[0].url.startswith("https://donkabel.ru/"):
        out = list(sp.site_page(html(out[0].url, "", out[0])))
    api = out[0]
    assert api.method == "POST" and api.url == discovery.YANDEX_SEARCH_URL and api.meta["dont_obey_robotstxt"]
    payload = json.dumps({"rawData": base64.b64encode(YANDEX_XML.encode()).decode()}).encode()
    nxt = list(sp.search_results(TextResponse(url=api.url, body=payload, encoding="utf-8", request=api)))
    assert [r.url for r in nxt] == ["https://donkabel-rnd.ru/"] and nxt[0].meta["disc"]["method"] == "search"


def test_auto_accept_needs_product_evidence():
    """Без модератора пишутся позиции с признаком товара: линейка, модель или характеристики на странице."""
    from collections import Counter
    from sync.sitecrawl import auto_accept, first_stem, tidy
    cands = [{"name": n, "decision": "accept", "specs": sp} for n, sp in [
        ("Компенсаторы осевые с патрубками", 0), ("Компенсатор сдвиговый", 0),          # линейка
        ("Жатка безрядковая SN-8400", 0),                                                 # модель
        ("Кран-балка подвесная", 6),                                                      # характеристики на странице
        ("Пресс-кит", 0), ("Навигация для водителей", 0), ("Прокатное производство", 0),  # меню, подразделение
        ("10 лет Договор поставки по счету Программа замещения", 0),                      # склеенные заголовки блоков
        ("Shohadaye Dezful Sugar", 0), ("Металлургия", 0), ("Металлоконструкции", 0)]]    # объект портфолио, разные слова
    fam = Counter(first_stem(c["name"]) for c in cands)
    assert [c["name"] for c in cands if auto_accept(c, fam)] == ["Компенсаторы осевые с патрубками", "Компенсатор сдвиговый",
                                                                  "Жатка безрядковая SN-8400", "Кран-балка подвесная"]
    assert tidy("Жатка Harvester SN-5400 — идеальное решение для уборки подсолнечника") == "Жатка Harvester SN-5400"


def test_names_cleaned_of_site_markup():
    """Название позиции — без имени сайта, цены, «Купить …», повтора подписи; документы, статьи и рубрики — не позиции."""
    from collections import Counter
    from sync.sitecrawl import auto_accept, junk, site_prefix, strip_prefix, tidy
    assert tidy("Купить дровяную отопительную печь Умка в кожухе") == "Дровяная отопительная печь Умка в кожухе"
    assert tidy("Купить турбину (турбокомпрессор) для Alfa Romeo") == "Турбина (турбокомпрессор) для Alfa Romeo"
    assert tidy('Водный велосипед "Дельфин" 135 000 р') == 'Водный велосипед "Дельфин"'
    assert tidy("Задвижка 30с41нж Ду 50 Ру 16") == "Задвижка 30с41нж Ду 50 Ру 16"                     # модель, не цена
    assert tidy("Крюк захват торцевой 2 т Крюк захват торцевой 2 т") == "Крюк захват торцевой 2 т"
    assert tidy("Продукция - Задвижки") == "Задвижки"
    for name in ["Опросный лист на ГРПБ", "Коробка ЕхКК-А РЭ", "Как выбрать кран", "Рубрика: Стойки", "Технические характеристики",
                 "1. назначение 2. варианты исполнений 3. параметры технические"]:
        assert junk(name), name
    assert not junk("Каскад насосов К-80")
    fam = Counter()
    for name in ["Производим мостовые краны по цене на 15% ниже рынка", 'Строительная компания "АрмСтрой"', "Баня под ключ в Воронеже: проекты и цены"]:
        assert not auto_accept({"name": name, "decision": "accept", "specs": 3}, fam), name
    names = ["СаратовСталь Рубрика: Стойки", "СаратовСталь Шкаф ШТК-М-42", "СаратовСталь Шкафы этажные"]
    p = site_prefix(names, "ООО «Саратов-Сталь»")
    assert [strip_prefix(n, p) for n in names] == ["Рубрика: Стойки", "Шкаф ШТК-М-42", "Шкафы этажные"]
    assert site_prefix(["Металлоформа 1ПБ30.20", "Металлоформа 2ПБ30.16", "Металлоформа 3ПБ40.20"], "ООО «Золотой Пояс»") is None   # линейка
    assert strip_prefix("БЕШТАУ M24FHD/BHM", site_prefix(["БЕШТАУ M24FHD/BHM"] * 3 + ["БЕШТАУ M24FHD/DHH"], "ООО «Бештау»")) == "БЕШТАУ M24FHD/BHM"
    assert strip_prefix("СаратовСталь Шкаф ШТК-М-42 Шкаф ШТК-М-42", p) == "Шкаф ШТК-М-42"             # подпись повторяет заголовок


def load_daemon():
    spec = importlib.util.spec_from_file_location("crawler_daemon", ROOT / "crawler" / "daemon.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_crawler_starts_after_each_finished_sync():
    """Ночной обход — после каждого законченного сбора из реестров и только один раз на сбор."""
    from datetime import datetime
    due = load_daemon().nightly_due
    st = {"state": "idle", "last_started_at": "2026-09-28T00:01:00+03:00"}
    assert due(st, False, None)                                                            # первый обход — после первого сбора
    assert due(st, False, datetime.fromisoformat("2026-09-27T05:10:00+03:00"))             # сбор начался позже прошлого обхода
    assert not due(st, False, datetime.fromisoformat("2026-09-28T05:10:00+03:00"))         # после этого сбора обход уже был
    assert not due({**st, "state": "running"}, False, None)                                # сбор ещё идёт
    assert not due(st, True, None)                                                         # занята блокировка сбора
    assert not due({"state": "idle"}, False, None)                                         # сбора ещё не было


def test_spider_takes_jobs_from_admin_queue(repo):
    """Задание из админ-панели: предприятие — указанное в задании или то, чей это сайт; чужой адрес отклоняется."""
    from pkdb import connect
    from pkcrawler.spiders.company_sites import CompanySitesSpider
    from sync.store import Store
    st = Store()
    with_site = next(k for k, c in sorted(st.companies.items()) if c.get("site"))
    site = st.companies[with_site]["site"].rstrip("/")
    cid = company_without_site()
    with connect("ingest") as g:
        g.execute("INSERT INTO crawl_job (id, url, organization_id) VALUES ('j-host', %s, NULL), ('j-org', %s, %s), "
                  "('j-none', 'https://example.org/page', NULL)", (f"{site}/catalog/", f"{BASE}/", cid))
        g.commit()
    got = {t["company_id"]: t for t in CompanySitesSpider(jobs="j-host,j-org,j-none").job_targets()}
    assert set(got) == {with_site, cid}
    assert got[with_site]["url"] == f"{site}/catalog/" and got[cid]["hosts"] == ["test-zavod.ru"]
    with connect("ingest") as g:
        job = {r["id"]: r for r in g.execute("SELECT id, status, note FROM crawl_job")}
    assert job["j-none"]["status"] == "FAILED" and "не относится к сайту предприятия" in job["j-none"]["note"]


def test_crawl_run_is_applied_to_catalog_right_away(repo, monkeypatch):
    """Задание → запуск краулера (crawl_run) → планировщик сбора сразу переносит найденное в карточки, один раз."""
    from pkdb import connect, ingest
    from sync import control, run
    from sync.store import Store
    daemon = load_daemon()
    cid = company_without_site()
    with connect("ingest") as g:
        g.execute("INSERT INTO crawl_job (id, url, organization_id) VALUES ('j1', %s, %s)", (f"{BASE}/", cid))
        jobs = ingest.crawl_jobs_take(g)
        g.commit()
    assert [j["status"] for j in jobs] == ["RUNNING"]
    calls = []
    monkeypatch.setattr(daemon.subprocess, "call", lambda cmd, cwd: calls.append(cmd) or seed_crawl(cid) or 0)   # вместо Scrapy — готовые страницы
    try:
        assert daemon.crawl("jobs", ["-a", "jobs=j1"], ["j1"])
        assert calls[0][-2:] == ["-a", "jobs=j1"]
        with connect("ingest") as g:
            r = ingest.crawl_run_last(g)
            assert (r["kind"], r["status"]) == ("jobs", "OK") and r["stats"]["pages"] == 5 and r["stats"]["sites_confirmed"] == 1
            assert g.execute("SELECT status FROM crawl_job WHERE id = 'j1'").fetchone()["status"] == "DONE"
        rid = control.crawl_to_apply()
        assert rid == r["id"]
        assert run.apply_crawl(rid) == {"sites": 1, "products": 2, "sites_to_moderate": 0}
        st = Store()
        assert st.companies[cid]["site"] == f"{BASE}/" and len([p for p in st.products[cid] if p["source_id"].startswith(f"{cid}-web-")]) == 2
        assert control.crawl_to_apply() is None                                               # второй раз не переносится
        with connect("ingest") as g:
            assert ingest.crawl_summary(g)["last_run"]["applied"] == {"sites": 1, "products": 2, "sites_to_moderate": 0}
    finally:
        clear_crawl(cid)
