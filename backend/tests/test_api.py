from app import main
from app.main import app, sanitize_text
from fastapi.testclient import TestClient

c = TestClient(app)
H = {"Authorization": "Bearer dev-user"}
A = {"Authorization": "Bearer dev-admin"}


def test_meta_and_catalog():
    m = c.get("/api/v1/meta").json()
    assert {"data_revision", "companies", "products", "sources"} <= set(m)
    # тестовый каталог: 12 из первичного сбора + 16 участников регионального отделения
    assert m["companies"] == 28 and m["data_revision"] >= 1
    r = c.get("/api/v1/companies?size=100").json()
    ids = [x["id"] for x in r["items"]]
    assert "vzmk" not in ids and "vzbt" not in ids  # UNVERIFIED / OUTDATED скрыты
    assert "vzbt" in [
        x["id"]
        for x in c.get("/api/v1/companies?include_unverified=true&status=OUTDATED&size=100").json()[
            "items"
        ]
    ]


def test_overview_uses_the_catalog_snapshot_and_includes_collection_state():
    meta = c.get("/api/v1/meta").json()

    response = c.get("/api/v1/overview")

    assert response.status_code == 200
    overview = response.json()
    assert overview["totals"]["companies"] == meta["companies"]
    assert "productSources" in overview
    assert "sync" in overview["collection"]


def test_catalog_text_search_with_unverified_companies_without_city():
    # у неподтверждённых записей (spbk, stimul) город неизвестен — поиск по тексту не должен падать
    r = c.get("/api/v1/companies", params={"include_unverified": "true", "q": "завод", "size": 100})
    assert r.status_code == 200, r.text
    assert (
        c.get(
            "/api/v1/companies", params={"include_unverified": "true", "sort": "name", "size": 100}
        ).status_code
        == 200
    )


def test_search_explains_and_never_invents():
    r = c.post(
        "/api/v1/search",
        json={
            "text": "Нужна трубная заготовка из стали 40Х, 500 тонн в месяц, Волгоградская область"
        },
    ).json()
    assert (
        r["query"]["okpd2"] == "24.10" and r["query"]["volume"] == 500 and r["query"]["unit"] == "т"
    )
    top = r["results"][0]
    assert top["company_id"] == "ko"
    cap = next(x for x in top["criteria"] if x["k"] == "CAPACITY_MATCH")
    assert cap["r"] == "none"  # мощность не опубликована — не выдумываем
    r2 = c.post("/api/v1/search", json={"text": "производство вертолётов"}).json()
    assert r2["results"] == [] and r2["message"]


def test_search_by_words_outside_dictionary():
    # наименований реестра Минпромторга нет в словаре разбора: слова запроса ищутся в названиях позиций
    r = c.post("/api/v1/search", json={"text": "Нужна камера соляного тумана, Волгоград"}).json()
    free = r["query"]["products"][0]
    assert (
        free["free"]
        and free["label"] == "камера соляного тумана"
        and "product" not in r["query"]["missing"]
    )
    top = r["results"][0]
    assert top["company_id"] == "specklimat" and top["products"][0] == "specklimat-6"
    assert next(x for x in top["criteria"] if x["k"] == "PRODUCT_MATCH")["r"] == "yes"
    # служебные слова заявки не ищутся; словарные запросы работают как раньше
    assert (
        c.post(
            "/api/v1/search/parse", json={"text": "производство и поставка оборудования"}
        ).json()["products"]
        == []
    )
    assert [
        p["label"]
        for p in c.post("/api/v1/search/parse", json={"text": "центробежный насос"}).json()[
            "products"
        ]
    ] == ["насос"]


def test_search_parse_endpoint_accepts_plain_query():
    r = c.post("/api/v1/search/parse", json={"text": "сварка и станки", "city": "Волгоград"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["raw"] == "сварка и станки" and body["engine"] == "rules"
    assert [t["label"] for t in body["technologies"]] == ["сварка"]


def test_parser_knows_all_synced_regions():
    # регионы, которые добавляет синхронизация с реестрами, распознаются так же, как на сайте
    for text, code in [
        ("насос, Ростовская область", "61"),
        ("насос, Саратов", "64"),
        ("насос, Воронеж", "36"),
    ]:
        assert c.post("/api/v1/search/parse", json={"text": text}).json()["region"] == code


def test_okved_vs_okpd2_separate():
    r = c.post("/api/v1/search", json={"text": "центробежный насос"}).json()
    by = {x["company_id"]: x for x in r["results"]}
    assert any(k["k"] == "EXACT_OKVED_MATCH" for k in by["livgm"]["criteria"])
    assert any(k["k"] == "COMPATIBLE_OKVED" for k in by["vnm"]["criteria"])
    assert all(
        k["r"] == "part" for k in by["vnm"]["criteria"] if k["k"] == "OKPD2_MATCH"
    )  # присвоенный код


def test_rbac_and_validation():
    assert c.post("/api/v1/offers", json={"title": "x"}).status_code == 401
    assert (
        c.post(
            "/api/v1/offers",
            headers=H,
            json={"title": "Прокат", "category": "Материалы", "okpd2": "abc"},
        ).status_code
        == 422
    )
    o = c.post(
        "/api/v1/offers", headers=H, json={"title": "Прокат круглый", "category": "Материалы"}
    ).json()
    assert o["price_value"] is None and o["price_source"] is None
    assert (
        c.patch(
            "/api/v1/admin/companies/vnm/status", headers=H, json={"status": "VERIFIED"}
        ).status_code
        == 403
    )
    assert (
        c.patch(
            "/api/v1/admin/companies/vnm/status", headers=A, json={"status": "VERIFIED"}
        ).status_code
        == 200
    )


def test_offer_text_is_cleaned_but_not_truncated():
    o = c.post(
        "/api/v1/offers",
        headers=H,
        json={
            "title": "  Прокат\x00 круглый  ",
            "category": "Материалы",
            "description": "Круг 40Х\r\nДиаметр:\t 50–200 мм\n\n\n\nГОСТ 2590",
        },
    ).json()
    assert o["title"] == "Прокат круглый"
    assert (
        o["description"] == "Круг 40Х\nДиаметр: 50–200 мм\n\nГОСТ 2590"
    )  # переводы строк сохраняются
    # слишком длинный текст отклоняется, а не обрезается молча
    assert (
        c.post(
            "/api/v1/offers",
            headers=H,
            json={"title": "Прокат", "category": "Материалы", "description": "x" * 5001},
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/v1/offers", headers=H, json={"title": "Прокат", "category": "М" * 251}
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/v1/offers", headers=H, json={"title": 12345, "category": "Материалы"}
        ).status_code
        == 422
    )


def test_offer_country_and_negotiable_price():
    o = c.post(
        "/api/v1/offers",
        headers=H,
        json={
            "title": "Прокат круглый",
            "category": "Материалы",
            "country": " Россия ",
            "price_value": 125000,
            "price_negotiable": True,
        },
    ).json()
    assert o["country"] == "Россия" and o["price_negotiable"] is True
    # без отметки торга цена окончательная
    assert (
        c.post(
            "/api/v1/offers",
            headers=H,
            json={"title": "Прокат круглый", "category": "Материалы", "price_value": 1},
        ).json()["price_negotiable"]
        is False
    )
    # у «Цены по запросу» пометки о торге нет
    assert (
        c.post(
            "/api/v1/offers",
            headers=H,
            json={"title": "Прокат круглый", "category": "Материалы", "price_negotiable": True},
        ).json()["price_negotiable"]
        is None
    )
    assert (
        c.post(
            "/api/v1/offers",
            headers=H,
            json={"title": "Прокат", "category": "Материалы", "country": "Р" * 61},
        ).status_code
        == 422
    )


def test_sanitize_text():
    assert sanitize_text(" a \t b\n c ") == "a b c"
    assert sanitize_text("a\r\nb", multiline=True) == "a\nb"
    assert sanitize_text(None) is None and sanitize_text(5) == 5


def test_tokens_come_from_environment():
    assert main.TOKENS == {"dev-user": "user", "dev-admin": "admin"}  # локально, без PK_TOKENS
