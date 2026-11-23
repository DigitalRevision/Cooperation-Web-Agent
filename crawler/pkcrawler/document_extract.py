"""Безопасное извлечение текста и таблиц из открытых финансовых документов."""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from html.parser import HTMLParser
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

FINANCIAL_LINK = re.compile(
    r"annual|financial|accounting|investor|disclos|segment|revenue|report|"
    r"годов|бухгалтер|финанс|инвестор|раскрыт|отч[её]т|выруч|сегмент|"
    r"пояснен|аудитор",
    re.I,
)
SUPPORTED = {".pdf", ".xlsx", ".csv", ".xml", ".json", ".html", ".htm"}
FINANCIAL_CONTEXT = re.compile(
    r"выручк|сегмент|вид(?:ы|ов)? деятельност|оквэд|revenue|segment|turnover|"
    r"бухгалтерск|финансов(?:ая|ой) отч[её]тност|annual report",
    re.I,
)
MAX_ROWS = 2000
MAX_COLS = 40
MAX_CELL = 2000


class _HTMLTables(HTMLParser):
    """Извлекает видимый текст и простые HTML-таблицы без выполнения встроенного содержимого."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.tables: list[dict] = []
        self.table: dict | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.caption: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table" and self.table is None:
            self.table = {"title": "HTML table", "rows": []}
        elif self.table is not None and tag == "tr":
            self.row = []
        elif self.row is not None and tag in ("td", "th"):
            self.cell = []
        elif self.table is not None and tag == "caption":
            self.caption = []

    def handle_data(self, data):
        value = data.strip()
        if not value:
            return
        self.text_parts.append(value)
        if self.cell is not None:
            self.cell.append(value)
        if self.caption is not None:
            self.caption.append(value)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join(self.cell)[:MAX_CELL])
            self.cell = None
        elif tag == "tr" and self.row is not None and self.table is not None:
            if any(self.row):
                self.table["rows"].append(self.row[:MAX_COLS])
            self.row = None
            if len(self.table["rows"]) >= MAX_ROWS:
                self.table["rows"] = self.table["rows"][:MAX_ROWS]
        elif tag == "caption" and self.caption is not None and self.table is not None:
            self.table["title"] = " ".join(self.caption)[:MAX_CELL] or self.table["title"]
            self.caption = None
        elif tag == "table" and self.table is not None:
            if self.table["rows"]:
                self.tables.append(self.table)
            self.table = None
            self.row = self.cell = self.caption = None


def financial_document_link(url: str, label: str = "") -> bool:
    """Разрешает только открытые файлы поддерживаемого формата с финансовыми признаками в имени или ссылке."""
    path = PurePosixPath(url.split("?", 1)[0].lower())
    return (path.suffix in SUPPORTED or not path.suffix) and bool(
        FINANCIAL_LINK.search(f"{path.name} {label}")
    )


def _suffix(url: str, content_type: str) -> str:
    suffix = PurePosixPath(url.split("?", 1)[0].lower()).suffix
    if suffix in SUPPORTED:
        return suffix
    return {
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "text/csv": ".csv",
        "application/csv": ".csv",
        "application/xml": ".xml",
        "text/xml": ".xml",
        "application/json": ".json",
    }.get(content_type.split(";", 1)[0].lower(), "")


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _xlsx_tables(data: bytes) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(x.file_size for x in archive.infolist()) > 40 * 1024 * 1024:
            raise ValueError("XLSX распаковывается больше допустимого лимита")
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = [
                "".join(t.text or "" for t in si.iter() if t.tag.endswith("}t")) for si in root
            ]
        tables = []
        for name in sorted(
            x for x in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", x)
        ):
            root = ET.fromstring(archive.read(name))
            rows = []
            for row in (x for x in root.iter() if x.tag.endswith("}row")):
                cells = [""] * MAX_COLS
                for cell in (x for x in row if x.tag.endswith("}c")):
                    ref = cell.attrib.get("r", "")
                    letters = re.match(r"[A-Z]+", ref)
                    if not letters:
                        continue
                    col = 0
                    for char in letters.group():
                        col = col * 26 + ord(char) - 64
                    col -= 1
                    if col >= MAX_COLS:
                        continue
                    val = next((x.text for x in cell if x.tag.endswith("}v")), "") or ""
                    if cell.attrib.get("t") == "s" and val.isdigit() and int(val) < len(shared):
                        val = shared[int(val)]
                    elif cell.attrib.get("t") == "inlineStr":
                        val = "".join(x.text or "" for x in cell.iter() if x.tag.endswith("}t"))
                    cells[col] = val[:MAX_CELL]
                while cells and not cells[-1]:
                    cells.pop()
                if any(cells):
                    rows.append(cells)
                if len(rows) >= MAX_ROWS:
                    break
            if rows:
                tables.append({"title": PurePosixPath(name).stem, "rows": rows})
        return tables


def _xml_tables(data: bytes) -> list[dict]:
    root = ET.fromstring(data)
    rows = []
    for element in root.iter():
        children = [x for x in list(element) if list(x) or (x.text and x.text.strip())]
        if not children or len(children) > MAX_COLS:
            continue
        values = []
        for child in children:
            text = " ".join(t.strip() for t in child.itertext() if t and t.strip())
            label = (
                child.attrib.get("name") or child.attrib.get("code") or child.tag.rsplit("}", 1)[-1]
            )
            values.append(f"{label}: {text}"[:MAX_CELL])
        if len(values) >= 2:
            rows.append(values)
        if len(rows) >= MAX_ROWS:
            break
    return [{"title": "XML", "rows": rows}] if rows else []


def _json_tables(data: bytes) -> list[dict]:
    root = json.loads(_decode(data))
    tables = []

    def visit(value, title="JSON"):
        if (
            isinstance(value, list)
            and value
            and all(isinstance(x, (dict, list)) for x in value[:MAX_ROWS])
        ):
            if all(isinstance(x, dict) for x in value[:MAX_ROWS]):
                keys = list(dict.fromkeys(k for row in value[:MAX_ROWS] for k in row))[:MAX_COLS]
                tables.append(
                    {
                        "title": title,
                        "rows": [keys]
                        + [
                            [str(row.get(k, ""))[:MAX_CELL] for k in keys]
                            for row in value[:MAX_ROWS]
                        ],
                    }
                )
            elif all(isinstance(x, list) for x in value[:MAX_ROWS]):
                tables.append(
                    {
                        "title": title,
                        "rows": [
                            [str(cell)[:MAX_CELL] for cell in row[:MAX_COLS]]
                            for row in value[:MAX_ROWS]
                        ],
                    }
                )
        elif isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, (dict, list)):
                    visit(child, str(key))

    visit(root)
    return tables


def extract_document(url: str, content_type: str, data: bytes) -> dict:
    """Извлекает машиночитаемые таблицы без исполнения макросов или активного содержимого."""
    suffix = _suffix(url, content_type)
    tables, text = [], ""
    if suffix == ".xlsx":
        tables = _xlsx_tables(data)
    elif suffix == ".csv":
        content = _decode(data)
        try:
            dialect = csv.Sniffer().sniff(content[:8192], delimiters=";,\t,")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.reader(io.StringIO(content), dialect))[:MAX_ROWS]
        tables = (
            [
                {
                    "title": "CSV",
                    "rows": [[cell[:MAX_CELL] for cell in row[:MAX_COLS]] for row in rows],
                }
            ]
            if rows
            else []
        )
        text = content[:200_000]
    elif suffix == ".xml":
        tables = _xml_tables(data)
    elif suffix == ".json":
        tables = _json_tables(data)
        text = _decode(data)[:200_000]
    elif suffix in (".html", ".htm") or content_type in ("text/html", "application/xhtml+xml"):
        parser = _HTMLTables()
        parser.feed(_decode(data)[:1_000_000])
        parser.close()
        tables = parser.tables[:100]
        text = " ".join(parser.text_parts)[:200_000]
    elif suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data), strict=False)
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:100])[:200_000]
        tables = [
            {
                "title": "PDF text",
                "rows": [
                    [line[:MAX_CELL]] for line in text.splitlines()[:MAX_ROWS] if line.strip()
                ],
            }
        ]
    if not text:
        text = "\n".join(
            " | ".join(str(cell) for cell in row)
            for table in tables
            for row in table["rows"][:MAX_ROWS]
        )[:200_000]
    return {
        "text": text,
        "tables": tables,
        "format": suffix.lstrip("."),
        "content_type": content_type,
    }
