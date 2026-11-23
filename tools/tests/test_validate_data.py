from __future__ import annotations

from tools.validate_data import validate_company


def test_validate_company_reports_broken_source_and_dictionary_links() -> None:
    company = {
        "id": "company-1",
        "verification_status": "VERIFIED",
        "inn": "3446003396",
        "ogrn": "1023404238384",
        "kpp": "344601001",
        "okved_main": "24.10.6",
        "okved_extra": ["99.99"],
        "status_code": "ACTIVE",
        "risk_signals": [{"code": "RISK", "level": "high", "source_id": "missing"}],
        "technologies": [{"name": "Штамповка", "source_id": "missing"}],
    }
    products = [
        {
            "id": "product-1",
            "source_id": "missing",
            "okpd2": {"code": "01.11"},
            "price": {"amount": 10},
        }
    ]

    errors = validate_company(company, products, [], {"24.10.6"}, set())

    assert errors == [
        "company-1: INN without registry source",
        "company-1.risk_signals.RISK: missing source",
        "company-1: extra OKVED 99.99 not in dictionary",
        "company-1: VERIFIED without readable official site",
        "company-1.technologies: missing source",
        "product-1: missing source",
        "product-1: OKPD2 not in dictionary",
        "product-1: price without source",
    ]
