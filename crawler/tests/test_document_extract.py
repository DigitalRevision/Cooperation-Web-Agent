import io
import sys
import zipfile
from types import SimpleNamespace

from crawler.pkcrawler.document_extract import extract_document, financial_document_link


def test_html_financial_pages_and_tables_are_supported():
    html = b"""<html><title>Annual report</title><p>Revenue by business segment</p>
    <table><caption>Revenue 2025</caption><tr><th>Activity</th><th>Revenue</th></tr>
    <tr><td>Metal parts</td><td>70</td></tr></table></html>"""
    result = extract_document("https://company.test/annual-report-2025.html", "text/html", html)
    assert result["format"] == "html"
    assert result["tables"][0]["title"] == "Revenue 2025"
    assert result["tables"][0]["rows"][1] == ["Metal parts", "70"]
    assert financial_document_link("https://company.test/annual-report-2025.html")
    assert not financial_document_link("https://company.test/manual.docx", "Manual")


def test_csv_xml_and_json_extract_rows():
    csv_result = extract_document("report.csv", "text/csv", b"segment;revenue\nMetal;70\n")
    assert csv_result["tables"][0]["rows"][1] == ["Metal", "70"]

    xml_result = extract_document(
        "report.xml",
        "application/xml",
        b"<root><row><segment>Metal</segment><revenue>70</revenue></row></root>",
    )
    assert xml_result["tables"] and any(
        "Metal" in cell for cell in xml_result["tables"][0]["rows"][0]
    )

    json_result = extract_document(
        "report.json", "application/json", b'{"segments":[{"activity":"Metal","revenue":70}]}'
    )
    assert json_result["tables"][0]["rows"] == [["activity", "revenue"], ["Metal", "70"]]


def test_xlsx_and_pdf_are_read_without_executing_document_content(monkeypatch):
    workbook = io.BytesIO()
    with zipfile.ZipFile(workbook, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            """<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
            <si><t>Activity</t></si><si><t>Revenue</t></si><si><t>Metal</t></si></sst>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
            <row><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
            <row><c r="A2" t="s"><v>2</v></c><c r="B2"><v>70</v></c></row>
            </sheetData></worksheet>""",
        )
    xlsx_result = extract_document("report.xlsx", "application/octet-stream", workbook.getvalue())
    assert xlsx_result["tables"][0]["rows"] == [["Activity", "Revenue"], ["Metal", "70"]]

    class _Page:
        def extract_text(self):
            return "Annual report 2025 revenue by segment"

    class _Reader:
        pages = [_Page()]

        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=_Reader))
    pdf_result = extract_document(
        "annual-report-2025.pdf",
        "application/pdf",
        b"not a real PDF; reader is isolated in this test",
    )
    assert "Annual report 2025" in pdf_result["text"]
    assert pdf_result["format"] == "pdf"
