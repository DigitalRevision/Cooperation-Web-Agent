"""Консервативные оценки масштаба бизнеса по доступным публичным показателям."""

from __future__ import annotations

from datetime import date

SCALE_ORDER = ("micro", "small", "medium", "large")
SCALE_LABELS = {
    "micro": "Микропредприятие",
    "small": "Малый бизнес",
    "medium": "Средний бизнес",
    "large": "Крупный бизнес",
}

# Пороговые значения из критериев, опубликованных ФНС: доход 120/800/2000 млн руб.,
# среднесписочная численность 15/100/250 человек. Это ориентир для оценки, а не замена реестру.
REVENUE_LIMITS_RUB = (120_000_000, 800_000_000, 2_000_000_000)
HEADCOUNT_LIMITS = (15, 100, 250)


def _tier(value: float, limits: tuple[int, int, int]) -> int:
    return next((i for i, limit in enumerate(limits) if value <= limit), 3)


def estimate_business_scale(
    registry: dict | None, today: date | None = None, okved_main: str | None = None
) -> dict:
    """Возвращает предварительную оценку только при сопоставимых публичных показателях.

    Учитываются бухгалтерская выручка (тыс. руб.) и численность одного отчётного года.
    Значение остаётся оценкой: бухгалтерская выручка не тождественна налоговому доходу,
    а сведения о долях владения и связанных организациях в каталоге отсутствуют.
    """
    registry = registry or {}
    if registry.get("msp_status") == "CONFIRMED" and registry.get("msp"):
        code = {
            "микропредприятие": "micro",
            "малое предприятие": "small",
            "среднее предприятие": "medium",
        }.get(str(registry["msp"]).strip().lower())
        if code:
            return {
                "category": code,
                "label": SCALE_LABELS[code],
                "status": "OFFICIAL",
                "source": "FNS_RMSP",
                "as_of": registry.get("msp_as_of"),
                "year": None,
            }

    if registry.get("msp_status") not in ("NOT_LISTED", "IN_REGISTER_NO_CATEGORY"):
        return {
            "category": "unknown",
            "label": "Не определён",
            "status": "INSUFFICIENT_DATA",
            "reason": "Официальная категория ФНС ещё не проверена",
        }

    headcount, hc_year = registry.get("headcount"), registry.get("headcount_year")
    finance = registry.get("finance") or []
    latest = max(
        (f for f in finance if f.get("revenue") is not None),
        key=lambda f: f.get("year", 0),
        default=None,
    )
    if (
        latest is None
        or headcount is None
        or hc_year is None
        or latest.get("year") != hc_year
        or float(latest["revenue"]) < 0
        or int(headcount) < 0
    ):
        return {
            "category": "unknown",
            "label": "Не определён",
            "status": "INSUFFICIENT_DATA",
            "reason": "Для оценки нужны выручка и численность за один год",
        }

    if int(headcount) > 250 and (okved_main or "").split(".")[0] in {"13", "14", "15", "56"}:
        return {
            "category": "unknown",
            "label": "Не определён",
            "status": "INSUFFICIENT_DATA",
            "year": int(latest["year"]),
            "reason": "Для этого ОКВЭД возможен отдельный предел численности; доля профильного дохода и условия владения не проверены",
        }

    revenue_rub = float(latest["revenue"]) * 1000
    tier = max(_tier(revenue_rub, REVENUE_LIMITS_RUB), _tier(int(headcount), HEADCOUNT_LIMITS))
    code = SCALE_ORDER[tier]
    return {
        "category": code,
        "label": SCALE_LABELS[code],
        "status": "ESTIMATED",
        "source": "FNS_GIRBO+FNS_HEADCOUNT",
        "year": int(latest["year"]),
        "revenue_rub": revenue_rub,
        "headcount": int(headcount),
        "updated_at": (today or date.today()).isoformat(),
        "reason": "Оценка по выручке бухгалтерской отчётности и среднесписочной численности; налоговый доход и структура владения не проверены",
    }


def summarize_financial_activities(records: list[dict] | None) -> dict | None:
    """Выбирает ведущее опубликованное направление, только если оно не аналитическое и не конфликтует."""
    eligible = [
        x
        for x in records or []
        if x.get("is_leading")
        and (x.get("okved_code") or x.get("activity_name"))
        and x.get("status") in ("CONFIRMED", "DECLARED")
        and (not x.get("conflict") or x.get("preferred") is True)
    ]
    if not eligible:
        return None
    newest_year = max((x.get("report_year") or 0) for x in eligible)
    latest = [x for x in eligible if (x.get("report_year") or 0) == newest_year]
    # Отдельная отчётность и консолидированная отчётность описывают разные периметры;
    # валюты также нельзя сравнивать без подтверждённого курса пересчёта.
    perimeters = {(x.get("scope") or "unknown", x.get("currency") or "RUB") for x in latest}
    if len(perimeters) != 1:
        return None
    report_ids = {x.get("report_id") or x.get("source_id") or x.get("id") for x in latest}
    if len(report_ids) != 1:
        priority = max(int(x.get("source_priority") or 0) for x in latest)
        preferred_reports = {
            x.get("report_id") or x.get("source_id") or x.get("id")
            for x in latest
            if int(x.get("source_priority") or 0) == priority
        }
        if len(preferred_reports) != 1:
            return None
        latest = [
            x
            for x in latest
            if (x.get("report_id") or x.get("source_id") or x.get("id")) in preferred_reports
        ]
    if len(latest) != 1:
        return None
    return latest[0]


def merge_financial_activities(existing: list[dict] | None, incoming: list[dict]) -> list[dict]:
    """Стабильно обновляет одинаковые документы и помечает противоречия, сохраняя оба источника."""
    by_id = {x.get("id"): dict(x) for x in (existing or []) if x.get("id")}
    for row in incoming:
        if row.get("id"):
            by_id[row["id"]] = dict(row)
    rows = list(by_id.values())
    groups: dict[tuple, list[dict]] = {}
    for row in rows:
        key = (
            row.get("report_year"),
            row.get("scope"),
            row.get("currency") or "RUB",
            row.get("okved_code") or (row.get("activity_name") or "").strip().casefold(),
        )
        groups.setdefault(key, []).append(row)
    for group in groups.values():
        values = {round(float(x["revenue"]), 6) for x in group if x.get("revenue") is not None}
        conflict = len(values) > 1
        priority = max((int(x.get("source_priority") or 0) for x in group), default=0)
        preferred = [x for x in group if int(x.get("source_priority") or 0) == priority]
        winner = preferred[0] if conflict and len(preferred) == 1 else None
        for row in group:
            row["conflict"] = conflict
            if conflict:
                row["preferred"] = row is winner
                row["conflict_resolution"] = "source_priority" if winner else "manual_review"
                if row is not winner:
                    row["status"] = "CONFLICT"
            else:
                row.pop("preferred", None)
                row.pop("conflict_resolution", None)
    return sorted(
        rows,
        key=lambda x: (x.get("report_year") or 0, x.get("activity_name") or "", x.get("id") or ""),
        reverse=True,
    )
