"""Проверка целостности каталога в `sm01_catalog`."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

REGISTRY_SOURCES = {
    "EGRUL_AGGREGATOR",
    "GISP",
    "FNS",
    "FNS_EGRUL",
    "FNS_PB",
    "FNS_GIRBO",
    "FNS_OPENDATA",
    "EFRSB",
}
COMPANY_STATUSES = {"VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED", "OUTDATED"}
REGISTRY_STATUSES = {"ACTIVE", "REORGANIZING", "LIQUIDATING", "BANKRUPTCY", "LIQUIDATED"}
SOURCE_LINKED_FIELDS = ("technologies", "materials", "capacities", "certificates", "sites")


def _validate_requisites(
    company: dict[str, Any],
    sources: list[dict[str, Any]],
    okved_codes: set[str],
) -> list[str]:
    """Проверяет форматы, контрольные суммы и наличие основных реквизитов компании."""
    errors: list[str] = []
    company_id = company["id"]

    if company["verification_status"] not in COMPANY_STATUSES:
        errors.append(f"{company_id}: bad status")
    if company.get("inn") and not re.fullmatch(r"\d{10}|\d{12}", company["inn"]):
        errors.append(f"{company_id}: bad INN")
    if company.get("ogrn") and not re.fullmatch(r"\d{13}|\d{15}", company["ogrn"]):
        errors.append(f"{company_id}: bad OGRN")

    from backend.app.validators import inn_ok, kpp_ok, ogrn_ok, okpo_ok

    if company.get("inn") and not inn_ok(company["inn"]):
        errors.append(f"{company_id}: INN checksum")
    if company.get("ogrn") and not ogrn_ok(company["ogrn"]):
        errors.append(f"{company_id}: OGRN checksum")
    if company.get("kpp") and not kpp_ok(company["kpp"]):
        errors.append(f"{company_id}: bad KPP")
    if company.get("okpo") and not okpo_ok(company["okpo"]):
        errors.append(f"{company_id}: OKPO checksum")
    if company.get("okved_main") and company["okved_main"] not in okved_codes:
        errors.append(f"{company_id}: OKVED not in dictionary")
    if company.get("inn") and not any(
        source["source_type"] in REGISTRY_SOURCES for source in sources
    ):
        errors.append(f"{company_id}: INN without registry source")
    return errors


def _validate_registry_facts(
    company: dict[str, Any], sources: list[dict[str, Any]], okved_codes: set[str]
) -> list[str]:
    """Проверяет согласованность статуса компании, сигналов риска и кодов ОКВЭД."""
    errors: list[str] = []
    company_id = company["id"]
    source_ids = {source["id"] for source in sources}
    status = company.get("status_code")

    if status and status not in REGISTRY_STATUSES:
        errors.append(f"{company_id}: bad status_code")
    if status == "LIQUIDATED" and company["verification_status"] != "OUTDATED":
        errors.append(f"{company_id}: liquidated but not OUTDATED")

    for signal in company.get("risk_signals") or []:
        if signal.get("level") not in {"high", "mid", "low"}:
            errors.append(f"{company_id}.risk_signals: bad level")
        if signal.get("source_id") not in source_ids:
            errors.append(f"{company_id}.risk_signals.{signal.get('code')}: missing source")
    for code in company.get("okved_extra") or []:
        if code not in okved_codes:
            errors.append(f"{company_id}: extra OKVED {code} not in dictionary")
    return errors


def _validate_source_links(company: dict[str, Any], sources: list[dict[str, Any]]) -> list[str]:
    """Проверяет ссылки компании на источники и подтверждение официального сайта."""
    errors: list[str] = []
    company_id = company["id"]
    source_ids = {source["id"] for source in sources}

    if company["verification_status"] == "VERIFIED" and not any(
        source["source_type"] == "OFFICIAL_SITE" and source["fetch_status"] == "OK"
        for source in sources
    ):
        errors.append(f"{company_id}: VERIFIED without readable official site")
    for field in SOURCE_LINKED_FIELDS:
        for value in company.get(field) or []:
            if value.get("source_id") not in source_ids:
                errors.append(f"{company_id}.{field}: missing source")
    return errors


def _validate_products(
    products: list[dict[str, Any]], source_ids: set[str], okpd2_codes: set[str]
) -> list[str]:
    """Проверяет связи товаров с источниками и справочником ОКПД2."""
    errors: list[str] = []
    for product in products:
        if product["source_id"] not in source_ids:
            errors.append(f"{product['id']}: missing source")
        product_code = (product.get("okpd2") or {}).get("code")
        if product_code and product_code not in okpd2_codes:
            errors.append(f"{product['id']}: OKPD2 not in dictionary")
        if product.get("price") and not product["price"].get("source_id"):
            errors.append(f"{product['id']}: price without source")
    return errors


def validate_company(
    company: dict[str, Any],
    products: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    okved_codes: set[str],
    okpd2_codes: set[str],
) -> list[str]:
    """Объединяет проверки реквизитов, реестровых фактов, источников и товаров."""
    return (
        _validate_requisites(company, sources, okved_codes)
        + _validate_registry_facts(company, sources, okved_codes)
        + _validate_source_links(company, sources)
        + _validate_products(products, {source["id"] for source in sources}, okpd2_codes)
    )


def main() -> int:
    """Загружает каталог и выводит найденные нарушения.

    Returns:
        Код завершения: 0 при корректных данных и 1 при найденных нарушениях.
    """
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from pkdb import catalog, connect

    with connect("catalog") as connection:
        companies, products, sources = catalog.load_companies(connection)
        dictionaries = catalog.load_dictionaries(connection)

    okved_codes = {
        code for code, name in dictionaries["okved"].items() if name
    }  # код без названия считается ошибкой данных
    okpd2_codes = set(dictionaries["okpd2"])
    errors = [
        error
        for company_id, company in companies.items()
        for error in validate_company(
            company,
            products[company_id],
            sources[company_id],
            okved_codes,
            okpd2_codes,
        )
    ]
    print(
        "\n".join(errors)
        or f"data OK: {len(companies)} предприятий, "
        f"{sum(map(len, products.values()))} позиций, {sum(map(len, sources.values()))} источников"
    )
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
