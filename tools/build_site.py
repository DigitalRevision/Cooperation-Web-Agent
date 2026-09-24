"""Сборка сайта: site/src/* -> site/dist/index.html (+ data.json из Git-репозитория данных)."""
import os, glob, shutil, base64
S = os.path.join(os.path.dirname(__file__), "..", "site")
tpl = open(f"{S}/src/template.html", encoding="utf-8").read()
css = open(f"{S}/src/style.css", encoding="utf-8").read()
js = "\n".join(open(p, encoding="utf-8").read() for p in sorted(glob.glob(f"{S}/src/0*.js")))
assert "</script" not in js.lower()
logo = open(f"{S}/src/logo.svg", encoding="utf-8").read().strip()
# Favicon — тот же логотип, встроенный как data URI (работает и в одностраничной сборке)
favicon = "data:image/svg+xml;base64," + base64.b64encode(logo.encode("utf-8")).decode("ascii")
out = tpl.replace("/*STYLE*/", css).replace("/*SCRIPT*/", js).replace("/*LOGO*/", logo).replace("/*FAVICON*/", favicon)
os.makedirs(f"{S}/dist", exist_ok=True)
open(f"{S}/dist/index.html", "w", encoding="utf-8").write(out)
shutil.copy(f"{S}/data.json", f"{S}/dist/data.json")
print("ok", len(out))
# Локальный предпросмотр с полным каркасом документа (на claude.ai каркас добавляется при публикации)
# Служебные теги (title, favicon, шрифты, стили) идут в <head>, разметка страницы — в <body>
cut = out.index("\n<!-- Шапка")
open(f"{S}/dist/preview.html", "w", encoding="utf-8").write('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n' + out[:cut] + "\n</head><body>" + out[cut:] + "</body></html>")
