from __future__ import annotations

import base64
from pathlib import Path

import pytest

from tools.build_site import build_site


def _site_root(root: Path, javascript: str = "window.ready = true;") -> Path:
    source = root / "src"
    source.mkdir(parents=True)
    (source / "template.html").write_text(
        "<!doctype html><html><head>/*STYLE*//*LOGO*//*FAVICON*/</head>\n"
        "<!-- Шапка --><script>/*SCRIPT*/</script></html>",
        encoding="utf-8",
    )
    (source / "style.css").write_text("body { color: inherit; }", encoding="utf-8")
    (source / "01-core.js").write_text(javascript, encoding="utf-8")
    (source / "logo.svg").write_text(
        '<svg width="10" height="10"><title>logo</title></svg>', encoding="utf-8"
    )
    (source / "favicon.svg").write_text("<svg><path/></svg>", encoding="utf-8")
    return root


def test_build_site_writes_page_preview_and_optional_assets(tmp_path: Path) -> None:
    root = _site_root(tmp_path)
    (root / "data.json").write_text("{}", encoding="utf-8")
    (root / "legal").mkdir()
    (root / "legal" / "privacy.html").write_text("privacy", encoding="utf-8")

    page = build_site(root)

    assert "body { color: inherit; }" in page
    assert "window.ready = true;" in page
    assert 'class="logo" role="img"' in page
    assert (
        "data:image/svg+xml;base64," + base64.b64encode(b"<svg><path/></svg>").decode("ascii")
        in page
    )
    assert (root / "dist" / "index.html").read_text(encoding="utf-8") == page
    assert "<body>" in (root / "dist" / "preview.html").read_text(encoding="utf-8")
    assert (root / "dist" / "data.json").read_text(encoding="utf-8") == "{}"
    assert (root / "dist" / "legal" / "privacy.html").read_text(encoding="utf-8") == "privacy"


def test_build_site_rejects_script_terminator_before_writing(tmp_path: Path) -> None:
    root = _site_root(tmp_path, "const unsafe = '</script>';")

    with pytest.raises(ValueError, match="закрывающий тег"):
        build_site(root)

    assert not (root / "dist").exists()


def test_build_site_rejects_invalid_preview_template_before_writing(tmp_path: Path) -> None:
    root = _site_root(tmp_path)
    template = root / "src" / "template.html"
    template.write_text("<!doctype html>/*STYLE*//*LOGO*//*FAVICON*//*SCRIPT*/", encoding="utf-8")

    with pytest.raises(ValueError):
        build_site(root)

    assert not (root / "dist").exists()
