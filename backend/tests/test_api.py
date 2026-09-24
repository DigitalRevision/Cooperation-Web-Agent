from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)
H = {"Authorization": "Bearer dev-user"}
A = {"Authorization": "Bearer dev-admin"}


def test_meta_and_catalog():
    m = c.get("/api/v1/meta").json()
    assert m["companies"] == 12
    r = c.get("/api/v1/companies").json()
    ids = [x["id"] for x in r["items"]]
    assert "vzmk" not in ids and "vzbt" not in ids          # UNVERIFIED / OUTDATED скрыты
    assert "vzbt" in [x["id"] for x in c.get("/api/v1/companies?include_unverified=true").json()["items"]]


def test_search_explains_and_never_invents():
    r = c.post("/api/v1/search", json={"text": "Нужна трубная заготовка из стали 40Х, 500 тонн в месяц, Волгоградская область"}).json()
    assert r["query"]["okpd2"] == "24.10" and r["query"]["volume"] == 500 and r["query"]["unit"] == "т"
    top = r["results"][0]
    assert top["company_id"] == "ko"
    cap = next(x for x in top["criteria"] if x["k"] == "CAPACITY_MATCH")
    assert cap["r"] == "none"                                  # мощность не опубликована — не выдумываем
    r2 = c.post("/api/v1/search", json={"text": "производство вертолётов"}).json()
    assert r2["results"] == [] and r2["message"]


def test_okved_vs_okpd2_separate():
    r = c.post("/api/v1/search", json={"text": "центробежный насос"}).json()
    by = {x["company_id"]: x for x in r["results"]}
    assert any(k["k"] == "EXACT_OKVED_MATCH" for k in by["livgm"]["criteria"])
    assert any(k["k"] == "COMPATIBLE_OKVED" for k in by["vnm"]["criteria"])
    assert all(k["r"] == "part" for k in by["vnm"]["criteria"] if k["k"] == "OKPD2_MATCH")   # присвоенный код


def test_chain_replace_supplier():
    ch = c.post("/api/v1/chains", headers=H, json={"title": "Насос", "buyer_city": "Волгоград", "nodes": [
        {"step": "Прокат", "organization_id": "ko", "product_id": "ko-round"},
        {"step": "Насос", "organization_id": "vnm", "product_id": "vnm-pumps"}]}).json()
    nid = ch["nodes"][1]["id"]
    alts = c.post(f"/api/v1/chains/{ch['id']}/nodes/{nid}/alternatives", headers=H).json()
    assert alts["current"]["company_id"] == "vnm"
    assert "livgm" in [a["company_id"] for a in alts["alternatives"]]
    new = c.post(f"/api/v1/chains/{ch['id']}/nodes/{nid}/replace", headers=H, json={"organization_id": "livgm", "reason": "поставщик отказался"}).json()
    assert new["nodes"][1]["organization_id"] == "livgm" and new["nodes"][0]["organization_id"] == "ko"
    assert new["nodes"][1]["history"][0]["from"] == "vnm"


def test_rbac_and_validation():
    assert c.post("/api/v1/offers", json={"title": "x"}).status_code == 401
    assert c.post("/api/v1/offers", headers=H, json={"title": "Прокат", "category": "Материалы", "okpd2": "abc"}).status_code == 422
    o = c.post("/api/v1/offers", headers=H, json={"title": "Прокат круглый", "category": "Материалы"}).json()
    assert o["price_value"] is None and o["price_source"] is None
    assert c.patch("/api/v1/admin/companies/vnm/status", headers=H, json={"status": "VERIFIED"}).status_code == 403
    assert c.patch("/api/v1/admin/companies/vnm/status", headers=A, json={"status": "VERIFIED"}).status_code == 200
