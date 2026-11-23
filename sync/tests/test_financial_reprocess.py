import json

from pkdb import connect
from sync.sitecrawl import reprocess_financials
from sync.store import Store


def test_financial_documents_can_be_reprocessed_without_duplicates(repo):
    company_id = "vnm"
    source_url = "https://vnm.example.test"
    document_url = f"{source_url}/annual-report-2025.html"
    store = Store()
    store.load([company_id])
    store.sources[company_id] = [
        source
        for source in store.sources[company_id]
        if source.get("source_type") != "OFFICIAL_SITE"
    ]
    store.sources[company_id].append(
        {
            "id": f"{company_id}-official-test",
            "source_type": "OFFICIAL_SITE",
            "source_url": source_url,
            "source_title": "Test company site",
        }
    )
    store.dirty.add(company_id)
    store.save()

    page = {
        "source_type": "OFFICIAL_SITE",
        "source_url": source_url,
        "source_title": "Test company site",
        "text": "Отдельная бухгалтерская отчётность за 2025 год. Выручка указана в тыс. руб.",
        "content_hash": "test-content-hash",
        "extracted": {
            "title": "Annual report 2025",
            "inn": [],
            "inn_matches_card": True,
            "financial_tables": [
                {
                    "title": "Выручка по видам деятельности",
                    "rows": [
                        ["Код ОКВЭД", "Вид деятельности", "Выручка за 2025 год, тыс. руб."],
                        ["28.15", "Производство оборудования", "700"],
                        ["46.69", "Оптовая торговля", "300"],
                    ],
                }
            ],
        },
    }
    with connect("ingest") as db:
        db.execute(
            "INSERT INTO crawl_page(company_id,url,fetch_status,content_hash,item) VALUES (%s,%s,'OK',%s,%s::jsonb)",
            (company_id, document_url, page["content_hash"], json.dumps(page, ensure_ascii=False)),
        )

    result = reprocess_financials(store, only={company_id}, log=lambda *_: None)
    assert result == {"companies": 1, "facts": 2}
    store.save()
    first = Store().companies[company_id]["registry"]["financial_activities"]
    assert len(first) == 2 and next(x for x in first if x["is_leading"])["okved_code"] == "28.15"

    result = reprocess_financials(store, only={company_id}, log=lambda *_: None)
    assert result == {"companies": 1, "facts": 2}
    store.save()
    second = Store().companies[company_id]["registry"]["financial_activities"]
    assert len(second) == 2 and [x["id"] for x in first] == [x["id"] for x in second]
