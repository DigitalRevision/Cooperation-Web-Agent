from app import main
from app.auth import staff_id
from fastapi.testclient import TestClient

from pkdb import tx

client = TestClient(main.app)
USER = {"Authorization": "Bearer dev-user"}
ADMIN = {"Authorization": "Bearer dev-admin"}

PAYLOAD = {
    "report_year": 2025,
    "scope": "entity",
    "document_url": "https://example.test/annual-report-2025.pdf",
    "activities": [
        {
            "okved_code": "28.15",
            "activity_name": "Производство оборудования",
            "revenue": 700,
            "share": 70,
        },
        {
            "okved_code": "46.69",
            "activity_name": "Оптовая торговля оборудованием",
            "revenue": 300,
            "share": 30,
        },
    ],
}


def test_financial_submission_requires_verified_company_rep_and_valid_distribution():
    no_rep = client.post(
        "/api/v1/companies/meteor/financial-submissions", headers=USER, json=PAYLOAD
    )
    assert no_rep.status_code == 403
    assert (
        client.get("/api/v1/companies/meteor/financial-submissions", headers=USER).status_code
        == 403
    )
    assert client.get("/api/v1/admin/financial-submissions", headers=USER).status_code == 403

    with tx("moderation") as db:
        db.execute(
            "INSERT INTO company_rep (user_id, company_id, company_name) VALUES (%s,%s,%s)",
            (staff_id("dev-user"), "meteor", "Test fixture company"),
        )

    invalid = {
        **PAYLOAD,
        "activities": [dict(PAYLOAD["activities"][0], share=80), PAYLOAD["activities"][1]],
    }
    assert (
        client.post(
            "/api/v1/companies/meteor/financial-submissions", headers=USER, json=invalid
        ).status_code
        == 422
    )
    bad_document = {**PAYLOAD, "document_url": "http://example.test/report.pdf"}
    assert (
        client.post(
            "/api/v1/companies/meteor/financial-submissions", headers=USER, json=bad_document
        ).status_code
        == 422
    )

    submitted = client.post(
        "/api/v1/companies/meteor/financial-submissions", headers=USER, json=PAYLOAD
    )
    assert submitted.status_code == 201, submitted.text
    submission = submitted.json()
    assert submission["status"] == "PENDING"

    company = client.get("/api/v1/companies/meteor").json()
    assert company["registry"]["leading_financial_activity"]["okved_code"] == "28.15"
    assert company["registry"]["leading_financial_activity"]["status"] == "DECLARED"

    queue = client.get("/api/v1/admin/financial-submissions", headers=ADMIN)
    assert queue.status_code == 200 and queue.json()[0]["id"] == submission["id"]
    reviewed = client.patch(
        f"/api/v1/admin/financial-submissions/{submission['id']}",
        headers=ADMIN,
        json={"status": "APPROVED", "comment": "Проверен тестовый документ"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "APPROVED"

    bundle = client.get("/api/v1/bundle").json()
    company_light = next(x for x in bundle["companies"] if x["id"] == "meteor")
    assert company_light["leading_financial_activity"]["status"] == "CONFIRMED"
    assert company_light["leading_financial_activity"]["okved_code"] == "28.15"


def test_ordinary_user_cannot_review_financial_claims():
    assert (
        client.patch(
            "/api/v1/admin/financial-submissions/not-a-uuid",
            headers=USER,
            json={"status": "APPROVED"},
        ).status_code
        == 403
    )
