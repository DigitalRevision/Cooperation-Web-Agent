/* ===== Поиск, рынки, заявки, предложения, сравнение ===== */

/* ---------- Поиск поставщика ---------- */
ROUTES.search = () => {
  const q = UI.lastQuery, res = UI.lastResults;
  return `<div class="wrap page">${crumbs(["#search", "Поиск поставщика"])}
  <h1 class="h1">Поиск поставщика</h1>
  <p class="muted" style="max-width:720px">Опишите потребность своими словами. Система разберёт запрос на параметры и найдёт предприятия только в проверенной базе. AI не добавляет фактов о предприятиях.</p>
  <form class="search" id="main-search" role="search" style="margin-top:16px">
    <label class="sr" for="sq">Потребность</label>
    <input id="sq" name="q" value="${esc(q?.raw || "")}" placeholder="Нужна стальная заготовка 500 тонн в месяц в Волгоградской области" autocomplete="off">
    <button class="btn pri" type="submit">Найти</button>
  </form>
  <div class="row" style="margin-top:8px">
    ${App.sample ? `<button class="btn sm" data-act="ai-parse">Разобрать с помощью AI (Claude)</button>` : ""}
    <label class="chk"><input type="checkbox" id="show-unv" ${App.showUnverified ? "checked" : ""}> Показывать неподтверждённые данные</label>
    ${q ? `<button class="btn sm txt" data-act="save-search">Сохранить поиск</button><a class="btn sm txt" href="#buy.new">Создать заявку из запроса</a>` : ""}
  </div>
  ${q ? queryChips(q) : ""}
  <div class="note" style="margin-top:16px">
    <div class="pipe"><span class="k">Запрос</span><i>→</i><span>AI Parser</span><i>→</i><span>Structured Query</span><i>→</i><span>Поиск по базе</span><i>→</i><span>ОКВЭД</span><i>→</i><span>ОКПД2</span><i>→</i><span>Продукция</span><i>→</i><span>Материал</span><i>→</i><span>Технология</span><i>→</i><span>География</span><i>→</i><span>Мощность</span><i>→</i><span class="k">Объяснимый результат</span></div>
  </div>
  ${res ? `<section class="sec" style="margin-top:32px">
    <div class="toolbar"><h2 class="h2">Найдено: ${res.length}</h2>
      <select class="sel" data-sort="search" aria-label="Сортировка">${[["match", "По степени соответствия требованиям"], ["distance", "По расстоянию от г. " + App.profile.city], ["data", "По количеству подтверждённых данных"], ["name", "По названию"]].map(([v, t]) => `<option value="${v}" ${UI.searchSort === v ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></div>
    ${res.length ? sortSearch(res).map(resultCard).join("") : `<div class="note">Информация не найдена в открытых источниках, собранных для базы. Уточните запрос или <a href="#buy.new">создайте заявку</a> — её увидят предприятия, которые подключатся к платформе.</div>`}
    ${res.length > 1 ? `<div class="row" style="margin-top:16px"><button class="btn" data-act="compare-results">Сравнить найденных поставщиков</button></div>` : ""}
  </section>` : ""}
  </div>`;
};
// Сортировка результатов поиска
function sortSearch(res) {
  const s = UI.searchSort || "match";
  const f = { match: (a, b) => b.yes - a.yes || a.applicable - b.applicable, distance: (a, b) => (a.dist ?? 1e9) - (b.dist ?? 1e9), data: (a, b) => completeness(b.c).n - completeness(a.c).n, name: (a, b) => a.c.short.localeCompare(b.c.short, "ru") }[s];
  return res.slice().sort(f);
}
// Карточка найденного предприятия с обоснованием совпадений
function resultCard(m) {
  const c = m.c;
  return `<article class="card" style="margin-bottom:16px">
    <div class="card-head"><div style="min-width:0"><h3 class="h3"><a href="#c.${c.id}">${esc(c.name)}</a></h3>
      <div class="muted">${esc(regionName(c.region))}, ${esc(c.city)}${m.dist != null ? " · " + esc(distTxt(m.dist, App.profile.city)) : ""} · ${okvedTag(c.okved_main)}</div></div>
      <div class="stack" style="align-items:flex-end">${statusBadge(c.verification_status)}<span class="score">${m.yes} из ${m.applicable}</span></div></div>
    ${m.prods.length ? `<div class="muted" style="margin:8px 0">Подходящие позиции: ${m.prods.slice(0, 4).map((p) => `<a href="#p.${p.id}">${esc(p.name)}</a>`).join(" · ")}</div>` : ""}
    <details style="margin-top:8px"><summary class="btn sm txt" style="display:inline-flex">Почему предприятие в результатах</summary><div style="margin-top:12px">${matchTable(m)}</div></details>
    <div class="row" style="margin-top:12px"><button class="btn sm pri" data-act="rfq" data-company="${c.id}">Запросить предложение</button><button class="btn sm" data-cmp="c:${c.id}">Сравнить</button><button class="btn sm" data-act="to-chain" data-company="${c.id}">В производственную цепочку</button></div>
  </article>`;
}
// Запуск поиска: разбор запроса (правила или AI) и переход на страницу результатов
async function runSearch(text, useAI) {
  let q = null;
  if (useAI && App.sample) {
    toast("AI разбирает запрос…");
    try { q = await parseWithClaude(text); } catch (e) { toast(e?.code === "not_granted" ? "AI-разбор не разрешён — использован разбор по правилам." : "AI недоступен — использован разбор по правилам."); }
  }
  q = q || parseQuery(text);
  UI.lastQuery = q;
  UI.lastResults = searchCompanies(q, { includeUnverified: App.showUnverified });
  if (location.hash !== "#search") location.hash = "#search"; else render();
}

/* ---------- Рынок сбыта ---------- */
function offerRow(o) {
  return `<article class="card flat" style="margin-bottom:8px"><div class="card-head"><div style="min-width:0"><span class="label">${esc(o.kind_label || "Предложение")}</span><h3 class="h3" style="font-size:16px">${esc(o.title)}</h3>
    <div class="muted">${esc(o.company_name || "Предприятие не указано")} · ${esc(o.city || "")} · ${fmtDate(o.created_at)}</div></div>${userTag()}</div>
    <div class="row" style="margin-top:8px">${o.okpd2 ? okpdTag({ code: o.okpd2, name: App.data.okpd2[o.okpd2] || "", status: "USER" }) : ""}<span>${priceHtml(o.price)}</span>${o.qty ? `<span class="muted">Объём: ${esc(o.qty)} ${esc(o.unit || "")}</span>` : ""}</div>
    <div class="row" style="margin-top:8px"><button class="btn sm" data-act="offer-open" data-id="${o.id}">Подробнее</button><button class="btn sm" data-act="rfq-offer" data-id="${o.id}">Запросить предложение</button></div></article>`;
}
// Страница рынка сбыта (предложения поставщиков)
ROUTES.sell = (arg) => {
  if (arg === "new") setTimeout(() => openOfferForm(), 0);
  const cats = ["Продукция", "Материалы", "Комплектующие", "Оборудование", "Производственные услуги", "Технологии", "Производственные мощности", "Свободные мощности", "Складские остатки"];
  const f = UI.sellFilter || "";
  const offers = App.offers.filter((o) => !f || o.kind_label === f).sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  return `<div class="wrap page">${crumbs(["#sell", "Рынок сбыта"])}
  <div class="sec-h"><div><div class="label">Продать</div><h1 class="h1">Рынок сбыта</h1></div><button class="btn pri" data-act="offer-new">Разместить предложение</button></div>
  <p class="muted" style="max-width:720px">Предприятия размещают продукцию, материалы, комплектующие, оборудование, услуги, технологии и свободные мощности. Предложения пользователей помечены «Указано пользователем» до проверки модератором.</p>
  <div class="tabs" role="tablist">${["", ...cats].map((c) => `<button role="tab" aria-selected="${f === c}" data-sellf="${esc(c)}">${c || "Все"}</button>`).join("")}</div>
  <div class="grid2" style="align-items:start">
    <section><h2 class="h2" style="margin-bottom:12px">Предложения пользователей (${offers.length})</h2>
      ${offers.length ? offers.map(offerRow).join("") : `<div class="note">В этой категории предложений нет.</div>`}</section>
    <section><h2 class="h2" style="margin-bottom:12px">Продукция предприятий из проверенной базы</h2>
      <p class="muted" style="margin-top:0">Что предприятия производят по данным официальных источников. Цены и объёмы не опубликованы — запрос направляется предприятию.</p>
      <ul class="list">${allProducts().filter((p) => !f || (f === "Производственные услуги" ? p.kind === "service" : f === "Продукция" ? p.kind === "product" : false)).slice(0, 14).map((p) => `<li><span><a href="#p.${p.id}">${esc(p.name)}</a><br><span class="muted">${esc(p.c.short)} · ${esc(p.c.city)}</span></span><button class="btn sm" data-act="rfq" data-product="${p.id}">Запросить</button></li>`).join("") || '<li><span class="muted">Нет подтверждённых позиций этой категории.</span></li>'}</ul>
      <p><a href="#products">Весь каталог продукции →</a></p></section>
  </div></div>`;
};
// Форма размещения предложения
function openOfferForm(prefill = {}) {
  const myCos = App.profile.companies.map((x) => App.C[x.company_id]).filter(Boolean);
  openPanel(`<div class="panel-h"><div><div class="label">Рынок сбыта</div><h2 class="h2">Новое предложение</h2></div><button class="x" data-close aria-label="Закрыть">×</button></div>
  <form id="offer-form" class="form">
    <div class="field full"><label for="of-title">Название *</label><input class="inp" id="of-title" name="title" required value="${esc(prefill.title || "")}"></div>
    <div class="field"><label for="of-kind">Категория *</label><select class="sel" id="of-kind" name="kind_label">${["Продукция", "Материалы", "Комплектующие", "Оборудование", "Производственные услуги", "Технологии", "Производственные мощности", "Свободные мощности", "Складские остатки"].map((x) => `<option>${x}</option>`).join("")}</select></div>
    <div class="field"><label for="of-co">Предприятие *</label><input class="inp" id="of-co" name="company_name" required list="of-cos" value="${esc(prefill.company_name || myCos[0]?.name || "")}"><datalist id="of-cos">${App.data.companies.map((c) => `<option value="${esc(c.name)}">`).join("")}</datalist></div>
    <div class="field full"><label for="of-desc">Описание</label><textarea class="inp" id="of-desc" name="description"></textarea></div>
    <div class="field"><label for="of-mat">Материал</label><input class="inp" id="of-mat" name="material"></div>
    <div class="field"><label for="of-okpd">ОКПД2</label><input class="inp" id="of-okpd" name="okpd2" placeholder="например 28.13" pattern="[0-9]{2}(\\.[0-9]{1,2}){0,3}"></div>
    <div class="field full"><label for="of-spec">Характеристики</label><textarea class="inp" id="of-spec" name="specs" placeholder="Параметр: значение — по одному на строку"></textarea></div>
    <div class="field"><label for="of-qty">Количество</label><input class="inp" id="of-qty" name="qty" inputmode="decimal"></div>
    <div class="field"><label for="of-unit">Единица</label><select class="sel" id="of-unit" name="unit">${["т", "кг", "шт", "м", "м²", "м³", "л", "комплект", "партия"].map((u) => `<option>${u}</option>`).join("")}</select></div>
    <div class="field"><label for="of-price">Цена, ₽ (пусто — «по запросу»)</label><input class="inp" id="of-price" name="price" inputmode="decimal"></div>
    <div class="field"><label for="of-punit">Цена за</label><input class="inp" id="of-punit" name="price_unit" placeholder="т, шт, комплект"></div>
    <div class="field"><label for="of-min">Минимальная партия</label><input class="inp" id="of-min" name="min_batch"></div>
    <div class="field"><label for="of-lp">Срок производства</label><input class="inp" id="of-lp" name="lead_prod" placeholder="например 30 дней"></div>
    <div class="field"><label for="of-ld">Срок поставки</label><input class="inp" id="of-ld" name="lead_deliv"></div>
    <div class="field"><label for="of-city">Город отгрузки</label><select class="sel" id="of-city" name="city">${Object.keys(App.data.cities).map((c) => `<option>${c}</option>`).join("")}</select></div>
    <div class="field"><label for="of-wh">Склад</label><select class="sel" id="of-wh" name="warehouse"><option value="">Не указан</option>${App.profile.warehouses.map((w) => `<option value="${esc(w.id)}">${esc(w.name)}</option>`).join("")}</select></div>
    <div class="field full"><label for="of-terms">Условия поставки</label><input class="inp" id="of-terms" name="terms" placeholder="самовывоз, доставка, Incoterms"></div>
    <div class="field full"><label for="of-docs">Документы и сертификаты</label><input class="inp" id="of-docs" name="docs" placeholder="номера сертификатов, ссылки"></div>
    <div class="full note">Предложение публикуется с пометкой «Указано пользователем» и проходит модерацию. Не указывайте данные, которые не можете подтвердить документами.</div>
    <div class="full row"><button class="btn pri" type="submit">Опубликовать предложение</button><button class="btn" type="button" data-close>Отмена</button></div>
  </form>`);
  $("#of-kind").value = prefill.kind_label || "Продукция";
}
// Подробности предложения в боковой панели
function offerDetails(id) {
  const o = App.offers.find((x) => x.id === id); if (!o) return;
  openPanel(`<div class="panel-h"><div><div class="label">${esc(o.kind_label)}</div><h2 class="h2">${esc(o.title)}</h2></div><button class="x" data-close aria-label="Закрыть">×</button></div>
  ${userTag()}
  <dl class="kv" style="margin-top:16px">
    <dt>Предприятие</dt><dd>${esc(o.company_name)}${o.company_id ? ` · <a href="#c.${o.company_id}" data-close>карточка</a>` : ""}</dd>
    <dt>Описание</dt><dd>${o.description ? esc(o.description) : unk("na")}</dd>
    <dt>Материал</dt><dd>${o.material ? esc(o.material) : unk("na")}</dd>
    <dt>ОКПД2</dt><dd>${o.okpd2 ? esc(o.okpd2) : unk("na")}</dd>
    <dt>Характеристики</dt><dd>${o.specs ? esc(o.specs).replace(/\n/g, "<br>") : unk("na")}</dd>
    <dt>Количество</dt><dd>${o.qty ? esc(o.qty + " " + (o.unit || "")) : unk("na")}</dd>
    <dt>Цена</dt><dd>${priceHtml(o.price)}</dd>
    <dt>Минимальная партия</dt><dd>${o.min_batch ? esc(o.min_batch) : unk("na")}</dd>
    <dt>Срок производства</dt><dd>${o.lead_prod ? esc(o.lead_prod) : unk("na")}</dd>
    <dt>Срок поставки</dt><dd>${o.lead_deliv ? esc(o.lead_deliv) : unk("na")}</dd>
    <dt>Город отгрузки</dt><dd>${esc(o.city || "")}</dd>
    <dt>Условия поставки</dt><dd>${o.terms ? esc(o.terms) : unk("na")}</dd>
    <dt>Документы</dt><dd>${o.docs ? esc(o.docs) : unk("na")}</dd>
    <dt>Модерация</dt><dd>${esc(o.status === "APPROVED" ? "Проверено модератором" : o.status === "REJECTED" ? "Отклонено" : "Ожидает проверки")}</dd>
  </dl>
  <div class="row" style="margin-top:16px"><button class="btn pri" data-act="rfq-offer" data-id="${o.id}">Запросить предложение</button>${o.author === App.uid ? `<button class="btn danger" data-act="offer-del" data-id="${o.id}">Снять с публикации</button>` : ""}</div>`);
}

/* ---------- Рынок приобретения ---------- */
function requestRow(r) {
  return `<article class="card flat" style="margin-bottom:8px"><div class="card-head"><div style="min-width:0"><span class="label">Заявка${r.target_company ? " предприятию" : ""}</span><h3 class="h3" style="font-size:16px"><a href="#r.${r.id}">${esc(r.what)}</a></h3>
    <div class="muted">${r.qty ? esc(r.qty + " " + (r.unit || "") + (r.period ? "/" + r.period : "")) + " · " : ""}${esc(r.region_name || "Регион не указан")} · ${fmtDate(r.created_at)}</div></div>${userTag()}</div>
    <div class="row" style="margin-top:8px"><a class="btn sm" href="#r.${r.id}">Открыть заявку</a><span class="muted">Откликов: ${(r.responses || []).length}</span></div></article>`;
}
// Страница рынка приобретения (заявки покупателей)
ROUTES.buy = (arg) => {
  if (arg === "new") setTimeout(() => openRequestForm(UI.lastQuery ? { what: UI.lastQuery.raw } : {}), 0);
  const reqs = App.requests.slice().sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  return `<div class="wrap page">${crumbs(["#buy", "Рынок приобретения"])}
  <div class="sec-h"><div><div class="label">Купить</div><h1 class="h1">Рынок приобретения</h1></div><button class="btn pri" data-act="request-new">Создать заявку</button></div>
  <p class="muted" style="max-width:720px">Потребности предприятий: материалы, комплектующие, производственные услуги, требования к поставщикам. После создания заявки система подбирает потенциальных поставщиков из проверенной базы.</p>
  ${reqs.length ? reqs.map(requestRow).join("") : `<div class="note">Заявок пока нет. Создайте первую — система сразу покажет подходящие предприятия.</div>`}
  </div>`;
};
// Форма создания заявки
function openRequestForm(prefill = {}) {
  openPanel(`<div class="panel-h"><div><div class="label">Рынок приобретения</div><h2 class="h2">${prefill.target_company ? "Запрос предложения" : "Новая заявка"}</h2>${prefill.target_company ? `<div class="muted">Адресат: ${esc(App.C[prefill.target_company]?.name)}</div>` : ""}</div><button class="x" data-close aria-label="Закрыть">×</button></div>
  <form id="request-form" class="form">
    <input type="hidden" name="target_company" value="${esc(prefill.target_company || "")}"><input type="hidden" name="target_product" value="${esc(prefill.target_product || "")}">
    <div class="field full"><label for="rq-what">Что требуется *</label><input class="inp" id="rq-what" name="what" required value="${esc(prefill.what || "")}"></div>
    <div class="field"><label for="rq-qty">Количество</label><input class="inp" id="rq-qty" name="qty" inputmode="decimal" value="${esc(prefill.qty || "")}"></div>
    <div class="field"><label for="rq-unit">Единица</label><select class="sel" id="rq-unit" name="unit">${["т", "кг", "шт", "м", "м²", "м³", "л", "комплект", "партия"].map((u) => `<option ${prefill.unit === u ? "selected" : ""}>${u}</option>`).join("")}</select></div>
    <div class="field"><label for="rq-per">Периодичность</label><select class="sel" id="rq-per" name="period"><option value="">Разово</option><option value="мес" ${prefill.period === "мес" ? "selected" : ""}>В месяц</option><option value="год" ${prefill.period === "год" ? "selected" : ""}>В год</option></select></div>
    <div class="field"><label for="rq-mat">Материал</label><input class="inp" id="rq-mat" name="material" value="${esc(prefill.material || "")}"></div>
    <div class="field"><label for="rq-okpd">ОКПД2</label><input class="inp" id="rq-okpd" name="okpd2" value="${esc(prefill.okpd2 || "")}" placeholder="например 24.10"></div>
    <div class="field full"><label for="rq-spec">Характеристики</label><textarea class="inp" id="rq-spec" name="specs"></textarea></div>
    <div class="field"><label for="rq-cert">Требуемые сертификаты</label><input class="inp" id="rq-cert" name="certs"></div>
    <div class="field"><label for="rq-dl">Срок</label><input class="inp" id="rq-dl" name="deadline" type="date"></div>
    <div class="field"><label for="rq-reg">Регион поставки</label><select class="sel" id="rq-reg" name="region">${Object.values(App.data.regions).map((r) => `<option value="${r.code}">${esc(r.name)}</option>`).join("")}<option value="">Любой</option></select></div>
    <div class="field"><label for="rq-city">Город поставки</label><select class="sel" id="rq-city" name="city">${Object.keys(App.data.cities).map((c) => `<option ${App.profile.city === c ? "selected" : ""}>${c}</option>`).join("")}</select></div>
    <div class="field"><label for="rq-dist">Допустимое расстояние, км</label><input class="inp" id="rq-dist" name="max_distance" inputmode="numeric"></div>
    <div class="field"><label for="rq-bud">Бюджет, ₽</label><input class="inp" id="rq-bud" name="budget" inputmode="decimal"></div>
    <div class="field full"><label for="rq-extra">Дополнительные требования</label><textarea class="inp" id="rq-extra" name="extra"></textarea></div>
    <div class="full row"><button class="btn pri" type="submit">${prefill.target_company ? "Отправить запрос" : "Создать заявку и подобрать поставщиков"}</button><button class="btn" type="button" data-close>Отмена</button></div>
  </form>`);
}
// Заявка → поисковый запрос для подбора поставщиков
function requestQuery(r) {
  const q = parseQuery([r.what, r.material, r.specs].filter(Boolean).join(" "));
  if (r.qty) { q.volume = Number(String(r.qty).replace(",", ".")); q.unit = r.unit; q.period = r.period || null; q.missing = q.missing.filter((m) => m.k !== "volume"); }
  if (r.okpd2 && App.data.okpd2[r.okpd2.slice(0, 5)]) q.okpd2 = r.okpd2.slice(0, 5);
  if (r.region) { q.region = r.region; q.regionName = regionName(r.region); q.missing = q.missing.filter((m) => m.k !== "region"); }
  return q;
}
// Страница заявки с подобранными поставщиками
ROUTES.r = (id) => {
  const r = App.requests.find((x) => x.id === id);
  if (!r) return `<div class="wrap page">${crumbs(["#buy", "Рынок приобретения"], ["", "Заявка"])}<div class="note">Заявка не найдена или ещё загружается.</div></div>`;
  const q = requestQuery(r);
  let res = searchCompanies(q, { includeUnverified: App.showUnverified, city: r.city });
  if (r.max_distance) res = res.filter((m) => m.dist == null || m.dist <= Number(r.max_distance));
  const mine = r.author === App.uid;
  return `<div class="wrap page">${crumbs(["#buy", "Рынок приобретения"], ["", "Заявка"])}
  <div class="card-head"><div><div class="label">Заявка${r.target_company ? " · адресована: " + esc(App.C[r.target_company]?.short || "") : ""}</div><h1 class="h1">${esc(r.what)}</h1><div class="muted">Создана ${fmtDate(r.created_at)}</div></div>${userTag()}</div>
  <div class="grid2 sec" style="margin-top:24px">
    <dl class="kv">
      <dt>Количество</dt><dd>${r.qty ? esc(`${r.qty} ${r.unit || ""}${r.period ? " в " + (r.period === "мес" ? "месяц" : "год") : ""}`) : unk("na")}</dd>
      <dt>Материал</dt><dd>${r.material ? esc(r.material) : unk("na")}</dd>
      <dt>ОКПД2</dt><dd>${r.okpd2 ? esc(r.okpd2) : unk("na")}</dd>
      <dt>Характеристики</dt><dd>${r.specs ? esc(r.specs) : unk("na")}</dd>
      <dt>Сертификаты</dt><dd>${r.certs ? esc(r.certs) : unk("na")}</dd>
      <dt>Срок</dt><dd>${r.deadline ? fmtDate(r.deadline) : unk("na")}</dd>
      <dt>Регион, город</dt><dd>${esc(r.region_name || "Любой")}, ${esc(r.city || "")}</dd>
      <dt>Допустимое расстояние</dt><dd>${r.max_distance ? esc(r.max_distance) + " км" : unk("na")}</dd>
      <dt>Бюджет</dt><dd>${r.budget ? esc(Number(r.budget).toLocaleString("ru-RU")) + " ₽" : unk("na")}</dd>
      <dt>Доп. требования</dt><dd>${r.extra ? esc(r.extra) : unk("na")}</dd>
    </dl>
    <div><h2 class="h2" style="margin-bottom:8px">Отклики (${(r.responses || []).length})</h2>
      ${(r.responses || []).map((x) => `<div class="card flat" style="margin-bottom:8px"><b>${esc(x.company)}</b> <span class="muted">${fmtDate(x.at)}</span><div>${esc(x.text)}</div>${x.price ? `<div>${priceHtml({ value: x.price, unit: r.unit })}</div>` : ""}</div>`).join("") || '<div class="note">Откликов пока нет.</div>'}
      <form id="respond-form" data-id="${r.id}" class="stack" style="margin-top:12px"><div class="label">Откликнуться на заявку</div>
        <input class="inp" name="company" required placeholder="Ваше предприятие" aria-label="Предприятие" list="of-cos2"><datalist id="of-cos2">${App.data.companies.map((c) => `<option value="${esc(c.name)}">`).join("")}</datalist>
        <textarea class="inp" name="text" required placeholder="Условия, сроки, документы" aria-label="Текст отклика"></textarea>
        <input class="inp" name="price" inputmode="decimal" placeholder="Цена за единицу, ₽ (необязательно)" aria-label="Цена">
        <button class="btn pri" type="submit">Отправить отклик</button></form>
      ${mine ? `<div class="row" style="margin-top:12px"><button class="btn danger sm" data-act="request-del" data-id="${r.id}">Закрыть заявку</button></div>` : ""}
    </div>
  </div>
  <section class="sec">
    <div class="sec-h"><h2 class="h2">Потенциальные поставщики из проверенной базы: ${res.length}</h2><span class="muted">Порядок — по числу подтверждённых критериев. Выбор за вами.</span></div>
    ${queryChips(q)}
    <div style="margin-top:16px">${res.map(resultCard).join("") || '<div class="note">Подходящих предприятий в базе не найдено. Заявка остаётся открытой для откликов.</div>'}</div>
  </section></div>`;
};

/* ---------- Сравнение ---------- */
ROUTES.compare = () => {
  const items = App.profile.compare.map((k) => { const [t, id] = k.split(":"); return t === "c" ? { t, c: App.C[id], k } : { t, p: App.P[id], c: App.C[App.P[id]?.company_id], k }; }).filter((x) => x.c);
  if (!items.length) return `<div class="wrap page">${crumbs(["#compare", "Сравнение"])}<h1 class="h1">Сравнение</h1><div class="note" style="margin-top:16px">Добавьте предприятия или продукцию кнопкой «Сравнить» в каталоге.</div></div>`;
  const rows = [
    ["Статус проверки", (x) => statusBadge(x.c.verification_status)],
    ["Позиция", (x) => x.p ? `<a href="#p.${x.p.id}">${esc(x.p.name)}</a>` : `<span class="muted">Предприятие целиком</span>`],
    ["Регион, город", (x) => esc(regionName(x.c.region) + ", " + x.c.city)],
    ["Расстояние от г. " + App.profile.city, (x) => { const d = distanceKm(App.profile.city, x.c.city); return d != null ? (d === 0 ? "в том же городе" : d + " км по прямой") : unk("na"); }],
    ["Основной ОКВЭД", (x) => okvedTag(x.c.okved_main)],
    ["ОКПД2", (x) => x.p ? okpdTag(x.p.okpd2) : [...new Set(x.c.products.filter((p) => p.okpd2).map((p) => p.okpd2.code))].join(", ") || unk("none")],
    ["Продукция", (x) => x.c.products.length + " поз."],
    ["Технологии", (x) => x.c.technologies.map((t) => esc(t.name)).join("; ") || unk("none")],
    ["Материалы", (x) => x.c.materials.map((t) => esc(t.name)).join(", ") || unk("none")],
    ["Параметры", (x) => x.p ? (x.p.params.map((a) => `${esc(a.name)}: ${a.value ? esc(a.value) : "—"}`).join("<br>") || unk("na")) : "—"],
    ["Цена", () => unk("price")],
    ["Мин. партия", () => unk("na")],
    ["Наличие", () => unk("none")],
    ["Срок производства", () => unk("na")],
    ["Срок поставки", () => unk("na")],
    ["Мощность", (x) => x.c.capacities.filter((a) => !a.historical).map((a) => esc(a.text)).join("; ") || unk("none")],
    ["Сертификаты", (x) => x.c.certificates.map((a) => esc(a.name)).join("<br>") || unk("none")],
    ["Заполнено полей", (x) => { const m = completeness(x.c); return `${m.n} из ${m.of}`; }],
    ["Расхождения источников", (x) => (x.c.discrepancies || []).length ? `<span class="v part">${x.c.discrepancies.length}</span>` : '<span class="v yes">нет</span>'],
  ];
  return `<div class="wrap page">${crumbs(["#compare", "Сравнение"])}
  <div class="sec-h"><h1 class="h1">Сравнение (${items.length})</h1><button class="btn sm" data-act="compare-clear">Очистить</button></div>
  <p class="muted">Объективные параметры из источников. Система не выбирает победителя.</p>
  <div class="tbl-wrap"><table class="tbl sticky"><thead><tr><th>Параметр</th>${items.map((x) => `<th style="min-width:220px;white-space:normal"><a href="#c.${x.c.id}">${esc(x.c.short)}</a><br><button class="btn sm txt" data-cmp="${x.k}">Убрать</button></th>`).join("")}</tr></thead>
  <tbody>${rows.map(([n, f]) => `<tr><td><b>${esc(n)}</b></td>${items.map((x) => `<td>${f(x)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>`;
};
