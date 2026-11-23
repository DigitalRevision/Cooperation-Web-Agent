from datetime import date

from sync.business_data import (
    estimate_business_scale,
    merge_financial_activities,
    summarize_financial_activities,
)
from sync.financials import extract_company_activities


def _record(**overrides):
    return {
        "id": "a",
        "report_year": 2025,
        "scope": "entity",
        "currency": "RUB",
        "revenue": 70,
        "activity_name": "Производство оборудования",
        "okved_code": "28.15",
        "is_leading": True,
        "status": "CONFIRMED",
        **overrides,
    }


def test_msp_absence_never_means_large_and_official_category_wins():
    missing = estimate_business_scale({"msp_status": "NOT_LISTED"}, date(2026, 1, 1))
    assert missing["category"] == "unknown" and missing["status"] == "INSUFFICIENT_DATA"

    official = estimate_business_scale(
        {
            "msp_status": "CONFIRMED",
            "msp": "микропредприятие",
            "finance": [{"year": 2025, "revenue": 9_000_000}],
            "headcount": 9000,
            "headcount_year": 2025,
        }
    )
    assert official["category"] == "micro" and official["status"] == "OFFICIAL"


def test_scale_estimate_requires_same_year_and_is_marked_preliminary():
    stale = estimate_business_scale(
        {
            "msp_status": "NOT_LISTED",
            "headcount": 40,
            "headcount_year": 2024,
            "finance": [{"year": 2025, "revenue": 100_000}],
        }
    )
    assert stale["category"] == "unknown"

    estimated = estimate_business_scale(
        {
            "msp_status": "NOT_LISTED",
            "headcount": 300,
            "headcount_year": 2025,
            "finance": [{"year": 2025, "revenue": 3_000_000}],
        },
        date(2026, 1, 1),
    )
    assert estimated["category"] == "large" and estimated["status"] == "ESTIMATED"
    assert "владения" in estimated["reason"]

    special = estimate_business_scale(
        {
            "msp_status": "NOT_LISTED",
            "headcount": 300,
            "headcount_year": 2025,
            "finance": [{"year": 2025, "revenue": 3_000_000}],
        },
        okved_main="56.10",
    )
    assert special["category"] == "unknown"


def test_segment_lead_can_be_named_without_inventing_okved_and_scopes_do_not_mix():
    named_segment = _record(okved_code=None, activity_name="Оптовые продажи запасных частей")
    assert summarize_financial_activities([named_segment]) == named_segment
    assert (
        summarize_financial_activities(
            [_record(), _record(id="b", scope="consolidated", revenue=100)]
        )
        is None
    )


def test_conflicting_financial_facts_are_retained_and_equal_priority_is_unresolved():
    conflict = merge_financial_activities(
        [_record(source_priority=2)],
        [{**_record(), "id": "b", "revenue": 80, "source_priority": 2}],
    )
    assert len(conflict) == 2 and all(x["conflict"] for x in conflict)
    assert summarize_financial_activities(conflict) is None

    resolved = merge_financial_activities(
        [_record(source_priority=1)],
        [{**_record(), "id": "b", "revenue": 80, "source_priority": 3}],
    )
    winner = next(x for x in resolved if x["preferred"])
    assert winner["revenue"] == 80 and winner["status"] == "CONFIRMED"
    assert summarize_financial_activities(resolved)["id"] == "b"


def test_lead_requires_one_report_and_unique_maximum():
    first = _record(id="a", report_id="report-a", source_priority=2)
    second = _record(
        id="b", report_id="report-b", source_priority=2, okved_code="46.69", revenue=80
    )
    assert summarize_financial_activities([first, second]) is None

    preferred = {**second, "source_priority": 3}
    assert summarize_financial_activities([first, preferred]) == preferred

    tie = _record(id="tie", report_id="report-tie", revenue=70)
    tied_leader = _record(id="tie-2", report_id="report-tie", okved_code="46.69", revenue=70)
    assert summarize_financial_activities([tie, tied_leader]) is None


def test_report_period_is_not_inferred_from_fetch_date_and_currency_conflicts_are_not_merged():
    page = {
        "status": "OK",
        "source_type": "OFFICIAL_SITE",
        "url": "https://example.test/disclosure.html",
        "source_url": "https://example.test",
        "source_title": "Disclosures",
        "fetched_at": "2026-11-01",
        "text": "Страница обновлена в 2026 году; выручка по сегментам.",
        "e": {
            "inn": [],
            "inn_matches_card": True,
            "title": "Disclosures",
            "financial_tables": [
                {
                    "title": "Выручка по сегментам",
                    "rows": [["Сегмент", "Выручка"], ["Производство", "70"], ["Продажи", "30"]],
                }
            ],
        },
    }
    assert extract_company_activities({"inn": "7700000000"}, {page["url"]: page}, []) == []

    usd = _record(id="usd", currency="USD", report_id="same")
    rub = _record(id="rub", currency="RUB", report_id="same", revenue=90)
    merged = merge_financial_activities([], [usd, rub])
    assert not any(row["conflict"] for row in merged)
    assert summarize_financial_activities(merged) is None


def test_financial_parser_uses_explicit_period_scope_currency_and_okved_column():
    company = {"inn": "7700000000"}
    page = {
        "status": "OK",
        "source_type": "OFFICIAL_SITE",
        "url": "https://example.test/report-2025.pdf",
        "source_url": "https://example.test",
        "source_title": "Annual report 2025",
        "fetched_at": "2026-11-01",
        "text": "Отдельная бухгалтерская отчетность за 2025 год. Выручка указана в тыс. руб.",
        "e": {
            "inn": ["7700000000"],
            "inn_matches_card": True,
            "title": "Annual financial report 2025",
            "financial_tables": [
                {
                    "title": "Выручка по видам деятельности",
                    "rows": [
                        [
                            "Код ОКВЭД",
                            "Вид деятельности",
                            "Выручка за 2025 год, тыс. руб.",
                            "Доля, %",
                        ],
                        ["28.15", "Производство оборудования", "700", "70"],
                        ["46.69", "Оптовая торговля", "300", "30"],
                    ],
                }
            ],
        },
    }
    sources = [
        {"id": "company-site", "source_type": "OFFICIAL_SITE", "source_url": "https://example.test"}
    ]
    facts = extract_company_activities(company, {page["url"]: page}, sources)
    assert len(facts) == 2
    assert facts[0]["report_year"] == 2025 and facts[0]["scope"] == "entity"
    assert facts[0]["currency"] == "RUB" and facts[0]["okved_code"] == "28.15"
    assert facts[0]["revenue"] == 700_000 and facts[0]["share"] == 70
    assert summarize_financial_activities(facts)["okved_code"] == "28.15"


def test_financial_parser_rejects_identity_mismatch_and_never_guesses_okved():
    page = {
        "status": "OK",
        "source_type": "OFFICIAL_SITE",
        "url": "https://example.test/annual-report-2025.html",
        "source_url": "https://example.test",
        "text": "Отчет за 2025 год. Выручка в рублях.",
        "e": {
            "inn": ["7800000000"],
            "inn_matches_card": False,
            "title": "Отчет за 2025 год",
            "financial_tables": [
                {
                    "title": "Выручка по сегментам",
                    "rows": [
                        ["Сегмент", "Выручка за 2025 год"],
                        ["Сервис", "70"],
                        ["Поставка", "30"],
                    ],
                }
            ],
        },
    }
    assert extract_company_activities({"inn": "7700000000"}, {page["url"]: page}, []) == []

    page["e"]["inn"] = ["7700000000"]
    page["e"]["inn_matches_card"] = True
    rows = extract_company_activities({"inn": "7700000000"}, {page["url"]: page}, [])
    assert len(rows) == 2
    assert all(x["okved_code"] is None for x in rows)
    assert summarize_financial_activities(rows)["activity_name"] == "Сервис"
