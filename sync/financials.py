"""Разбор явной выручки по сегментам/ОКВЭД из документов с подтверждённых сайтов."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

ACTIVITY = re.compile(r"вид(?:ы|ов)? деятельност|сегмент|оквэд|business segment|activity", re.I)
REVENUE = re.compile(r"выручк|revenue|turnover", re.I)
SHARE = re.compile(r"дол[яи]|share|%", re.I)
CODE = re.compile(r"^(\d{2}(?:\.\d{1,2}){0,3})$")
YEAR = re.compile(r"\b(20\d{2})\b")
REPORT_YEAR = re.compile(
    r"(?:за|for(?: the)?|year ended|reporting period|отч[её]тн(?:ый|ого) период)\D{0,35}(20\d{2})"
    r"|(20\d{2})\D{0,16}(?:год|year|financial|fiscal)",
    re.I,
)
REPORT_CONTEXT = re.compile(
    r"отч[её]т|accounting|annual|financial|fiscal|year ended|reporting period", re.I
)
TOTAL = re.compile(r"^(?:итого|всего|total|grand total)\b", re.I)


def _norm(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\xa0", " ")).strip()


def _number(value) -> float | None:
    text = _norm(value).replace("−", "-")
    if not text or text in {"—", "–", "-", "н/д", "n/a"}:
        return None
    match = re.search(r"\(?-?\d[\d\s.,]*\d|\d\)?", text)
    if not match:
        return None
    raw = match.group(0).replace(" ", "")
    negative = raw.startswith("(") or raw.startswith("-")
    raw = raw.strip("()").lstrip("-")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")
    try:
        result = float(raw)
    except ValueError:
        return None
    return -result if negative else result


def _amount_unit(text: str) -> tuple[str, float]:
    x = text.lower().replace("ё", "е")
    currency = (
        "RUB"
        if re.search(r"руб|₽|\brub\b|\brur\b", x)
        else "USD"
        if re.search(r"\$|\busd\b|доллар", x)
        else "EUR"
        if re.search(r"€|\beur\b|евро", x)
        else "CNY"
        if re.search(r"юан|\bcny\b", x)
        else "UNKNOWN"
    )
    scale = (
        1_000_000_000
        if re.search(r"млрд|billion", x)
        else 1_000_000
        if re.search(r"млн|million", x)
        else 1_000
        if re.search(r"тыс\.?|thousand", x)
        else 1
    )
    return currency, scale


def _scope(text: str) -> str:
    x = text.lower().replace("ё", "е")
    if re.search(r"консолидирован|consolidated", x):
        return "consolidated"
    if re.search(r"отдельн(?:ая|ой) бухгалтерск|неконсолидирован|standalone|separate financial", x):
        return "entity"
    return "unknown"


def _report_year(text: str, url: str, title: str | None) -> int | None:
    """Определяет год только по явной подписи отчётного периода или названию документа."""
    named = f"{title or ''} {url}"
    if re.search(r"annual|financial|accounting|отч[её]т|бухгалтер", named, re.I):
        years = [int(x) for x in YEAR.findall(named)]
        if years:
            return max(years)
    # Упоминание «страница обновлена в 2026 году» рядом с выручкой не задаёт отчётный период.
    # Текстовый период принимается только из строки с явным контекстом отчётности; годовые заголовки
    # финансовой таблицы обрабатываются отдельно ниже.
    periods = [
        int(y)
        for line in text.splitlines()
        if REPORT_CONTEXT.search(line)
        for match in REPORT_YEAR.finditer(line)
        for y in match.groups()
        if y
    ]
    return max(periods) if periods else None


def _rows(table: dict) -> list[list[str]]:
    result = []
    for row in table.get("rows") or []:
        if isinstance(row, (list, tuple)):
            result.append([_norm(x) for x in row])
        elif isinstance(row, dict):
            result.append([_norm(k) + ": " + _norm(v) for k, v in row.items()])
    # PDF extraction often returns a single string per line; preserve likely columns separated by spacing/pipes.
    out = []
    for row in result:
        if len(row) == 1:
            parts = [_norm(x) for x in re.split(r"\s{2,}|\s*\|\s*", row[0]) if _norm(x)]
            out.append(parts if len(parts) > 1 else row)
        else:
            out.append(row)
    return out


@dataclass(frozen=True)
class TableLayout:
    """??????? ??????????? ? ???????? ??????, ???????????? ? ????????? ???????."""

    header_end: int
    headers: list[str]
    activity_col: int
    okved_col: int | None
    revenue_col: int
    share_col: int | None
    year: int


def _table_layout(
    rows: list[list[str]], sample: str, report_year: int | None
) -> TableLayout | None:
    """Определяет столбцы и год отчётности по заголовкам без придуманых периодов."""
    header_end = 0
    for index, row in enumerate(rows[:3]):
        joined = " ".join(row)
        if REVENUE.search(joined) or ACTIVITY.search(joined) or YEAR.search(joined):
            header_end = index
    width = max(map(len, rows[: max(4, header_end + 1)]))
    headers = [
        " ".join(row[i] for row in rows[: header_end + 1] if i < len(row)) for i in range(width)
    ]
    activity_col = next((i for i, header in enumerate(headers) if ACTIVITY.search(header)), 0)
    okved_col = next(
        (
            i
            for i, header in enumerate(headers)
            if re.search(
                r"\u0420\u0455\u0420\u0454\u0420\u0406\u0421\u040c\u0420\u0491", header, re.I
            )
        ),
        None,
    )
    revenue_cols = [i for i, header in enumerate(headers) if REVENUE.search(header)]
    year_headers = [
        (max(int(year) for year in YEAR.findall(header)), i)
        for i, header in enumerate(headers)
        if YEAR.search(header)
    ]
    if REVENUE.search(sample):
        revenue_cols = sorted(set(revenue_cols + [i for _, i in year_headers]))
    if not revenue_cols:
        return None

    share_col = next((i for i, header in enumerate(headers) if SHARE.search(header)), None)
    year_cols = [(year, i) for year, i in year_headers if i in revenue_cols]
    year = max((item[0] for item in year_cols), default=report_year)
    revenue_col = next(
        (i for column_year, i in year_cols if column_year == year),
        revenue_cols[-1] if len(revenue_cols) > 1 else revenue_cols[0],
    )
    if year is None:
        return None
    return TableLayout(header_end, headers, activity_col, okved_col, revenue_col, share_col, year)


def _activity_code(row: list[str], layout: TableLayout, label: str) -> tuple[str | None, str]:
    """????????? ??? ?????? ?? ?????????? ?????? ??? ?????? ? ????? ?????."""
    code = None
    if layout.okved_col is not None and layout.okved_col < len(row):
        match = CODE.fullmatch(_norm(row[layout.okved_col]))
        code = match[1] if match else None
    if code is None:
        match = CODE.fullmatch(label)
        code = match[1] if match else None
        if code:
            label = ""
    if re.search(
        r"\u0420\u0455\u0420\u0454\u0420\u0406\u0421\u040c\u0420\u0491",
        layout.headers[layout.activity_col],
        re.I,
    ):
        match = CODE.fullmatch(label)
        if match:
            code = match[1]
            label = ""
    return code, label


def _table_segments(
    rows: list[list[str]],
    layout: TableLayout,
    currency: str,
    multiplier: float,
) -> tuple[list[dict], float | None]:
    """Нормализует строки сегментов и возвращает их итоговую выручку."""
    candidates, total = [], None
    for row in rows[layout.header_end + 1 :]:
        if max(layout.activity_col, layout.revenue_col) >= len(row):
            continue
        label = _norm(row[layout.activity_col])
        amount = _number(row[layout.revenue_col])
        if any(TOTAL.match(_norm(cell)) for cell in row):
            total = amount
            continue
        if not label or amount is None:
            continue
        code, label = _activity_code(row, layout, label)
        label = re.sub(r"^\s*\d{2}(?:\.\d{1,2}){1,3}\s*[-–:]\s*", "", label).strip(" -–:")
        if not label and not code:
            continue
        explicit_share = (
            _number(row[layout.share_col])
            if layout.share_col is not None and layout.share_col < len(row)
            else None
        )
        candidates.append(
            {
                "activity_name": label or None,
                "okved_code": code,
                "revenue": round(amount * multiplier, 6),
                "share": explicit_share,
                "currency": currency,
            }
        )
    return candidates, total


def _serialize_table_segments(
    candidates: list[dict],
    total: float | None,
    multiplier: float,
    source: dict,
    year: int,
    scope: str,
    table_index: int,
) -> list[dict]:
    """Создаёт идентификаторы и полные факты сегментов после проверки их долей."""
    if total and total > 0:
        for row in candidates:
            if row["share"] is None:
                row["share"] = round(row["revenue"] / (total * multiplier) * 100, 4)
    elif all(row["share"] is None for row in candidates):
        # Доля от суммы сегментов не равна доле в общей выручке, поэтому не вычисляется без итога.
        pass
    lead = max(candidates, key=lambda x: x["revenue"])
    unique_leader = sum(x["revenue"] == lead["revenue"] for x in candidates) == 1
    report_id = hashlib.sha256(
        f"{source.get('url')}|{year}|{scope}|{table_index}".encode()
    ).hexdigest()[:20]
    out = []
    for row in candidates:
        activity_key = row["okved_code"] or row["activity_name"] or ""
        record_id = hashlib.sha256(f"{report_id}|{activity_key.casefold()}".encode()).hexdigest()
        out.append(
            {
                "id": record_id,
                "report_id": report_id,
                "report_year": year,
                **row,
                "unit": "base_currency",
                "scope": scope,
                "is_leading": row is lead and unique_leader,
                "source_url": source.get("url"),
                "source_title": source.get("title") or source.get("url"),
                "source_type": "COMPANY_SITE",
                "source_id": source.get("source_id"),
                "source_priority": 2,
                "source_date": source.get("fetched_at"),
                "updated_at": source.get("fetched_at"),
                "content_hash": source.get("content_hash"),
                "status": "DECLARED",
                "method": "explicit_okved_revenue_table"
                if row["okved_code"]
                else "explicit_segment_revenue_table",
                "identity": "inn_match" if source.get("inn_matches_card") else "confirmed_site",
                "table_index": table_index,
            }
        )
    return out


def _table_facts(
    table: dict, document_text: str, report_year: int | None, source: dict, table_index: int
) -> list[dict]:
    """Извлекает финансовые показатели из таблицы бухгалтерской отчётности.

    Строки и периоды нормализуются до фактов с названием показателя, годом,
    значением и единицей измерения; неподходящие таблицы возвращают пустой список.
    """
    rows = _rows(table)
    if len(rows) < 3:
        return []
    sample = " ".join([_norm(table.get("title")), " ".join(" ".join(row) for row in rows[:8])])
    if not REVENUE.search(sample) or not ACTIVITY.search(sample):
        return []
    layout = _table_layout(rows, sample, report_year)
    if layout is None:
        return []

    unit_text = " ".join([document_text[:5000], sample])
    currency, multiplier = _amount_unit(unit_text)
    scope = _scope(document_text[:10000] + " " + sample)
    candidates, total = _table_segments(rows, layout, currency, multiplier)
    if len(candidates) < 2:
        return []
    return _serialize_table_segments(
        candidates, total, multiplier, source, layout.year, scope, table_index
    )


def extract_company_activities(
    company: dict, pages: dict[str, dict], sources: list[dict] | None = None
) -> list[dict]:
    """Извлекает только табличную разбивку с подтверждённого сайта, отбрасывая явное несовпадение ИНН."""
    all_facts = []
    inn = str(company.get("inn") or "")
    for page in pages.values():
        extracted = page.get("e") or {}
        if page.get("status") != "OK" or page.get("source_type") != "OFFICIAL_SITE":
            continue
        page_inns = {str(x) for x in extracted.get("inn") or []}
        if extracted.get("inn_matches_card") is False or (
            inn and page_inns and inn not in page_inns
        ):
            continue
        text = page.get("text") or ""
        report_year = _report_year(
            text[:20000],
            page.get("url", ""),
            extracted.get("title") or extracted.get("h1") or page.get("source_title"),
        )
        source_id = next(
            (
                s.get("id")
                for s in sources or []
                if s.get("source_type") == "OFFICIAL_SITE"
                and s.get("source_url") == page.get("source_url")
            ),
            None,
        )
        fetched_at = page.get("fetched_at")
        if hasattr(fetched_at, "isoformat"):
            fetched_at = fetched_at.isoformat()
        source = {
            "url": page.get("url"),
            "title": extracted.get("title") or extracted.get("h1") or page.get("source_title"),
            "fetched_at": page.get("fetched_at"),
            "content_hash": page.get("content_hash"),
            "inn_matches_card": extracted.get("inn_matches_card"),
            "source_id": source_id,
        }
        source["fetched_at"] = fetched_at
        for index, table in enumerate(extracted.get("financial_tables") or []):
            all_facts.extend(_table_facts(table, text, report_year, source, index))
    # Для каждой таблицы выбран ведущий сегмент; дубликаты в разных обходах одной страницы схлопываются по стабильному id.
    return list({x["id"]: x for x in all_facts}.values())
