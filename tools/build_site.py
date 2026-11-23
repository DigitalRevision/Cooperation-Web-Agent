"""Сборка одностраничного сайта из исходников `site/src/`."""

from __future__ import annotations

import base64
import re
import shutil
from pathlib import Path

if __package__:
    from .atomic_files import atomic_copy, atomic_write_text
else:
    from atomic_files import atomic_copy, atomic_write_text

SITE_ROOT = Path(__file__).resolve().parents[1] / "site"
_XML_DECLARATION = re.compile(r"^<\?xml[^>]*\?>\s*")
_SVG_ROOT_ATTRIBUTES = re.compile(r'\s(width|height|class|role|aria-label)="[^"]*"')


def _inline_logo(source: str) -> str:
    """Подготавливает логотип для встраивания в HTML с доступным именем."""
    svg = _XML_DECLARATION.sub("", source.strip())

    def replace_root(match: re.Match[str]) -> str:
        tag = _SVG_ROOT_ATTRIBUTES.sub("", match.group(0))
        return tag[:-1] + ' class="logo" role="img" aria-label="Союз машиностроителей России">'

    return re.sub(r"<svg\b[^>]*>", replace_root, svg, count=1)


def _favicon_data_uri(source: str) -> str:
    """Кодирует SVG favicon, чтобы иконка работала в собранном HTML-файле."""
    svg = _XML_DECLARATION.sub("", source.strip())
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def _preview_document(page: str) -> str:
    """Оборачивает каркас сайта в полный HTML для локального предпросмотра."""
    body_start = page.index("\n<!-- Шапка")
    return (
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
        + page[:body_start]
        + "\n</head><body>"
        + page[body_start:]
        + "</body></html>"
    )


def build_site(site_root: Path = SITE_ROOT) -> str:
    """Собирает и сохраняет одностраничную версию сайта.

    Args:
        site_root: Каталог сайта с исходниками в `src/`.

    Returns:
        Собранный HTML, также записанный в `dist/index.html`.

    Raises:
        ValueError: Если в скриптах есть закрывающий тег `script` или в шаблоне нет маркера шапки.
    """
    source_dir = site_root / "src"
    template = (source_dir / "template.html").read_text(encoding="utf-8")
    css = (source_dir / "style.css").read_text(encoding="utf-8")
    scripts = sorted(source_dir.glob("0*.js"))
    javascript = "\n".join(path.read_text(encoding="utf-8") for path in scripts)
    if "</script" in javascript.lower():
        raise ValueError("Исходные скрипты содержат закрывающий тег script")

    logo = _inline_logo((source_dir / "logo.svg").read_text(encoding="utf-8"))
    favicon = _favicon_data_uri((source_dir / "favicon.svg").read_text(encoding="utf-8"))
    page = (
        template.replace("/*STYLE*/", css)
        .replace("/*SCRIPT*/", javascript)
        .replace("/*LOGO*/", logo)
        .replace("/*FAVICON*/", favicon)
    )
    # Проверяем маркер до записи, чтобы при сломанном шаблоне не оставить частичную сборку.
    preview = _preview_document(page)

    dist_dir = site_root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(dist_dir / "index.html", page)
    atomic_write_text(dist_dir / "preview.html", preview)

    data_file = site_root / "data.json"
    if data_file.exists():
        atomic_copy(data_file, dist_dir / data_file.name)

    legal_dir = site_root / "legal"
    if legal_dir.is_dir():
        shutil.copytree(legal_dir, dist_dir / legal_dir.name, dirs_exist_ok=True)
    return page


def main() -> None:
    """Выполняет сборку сайта из командной строки."""
    page = build_site()
    print("ok", len(page))


if __name__ == "__main__":
    main()
