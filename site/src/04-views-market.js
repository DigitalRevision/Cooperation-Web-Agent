/* ===== Поиск, рынки, заявки, предложения, сравнение ===== */

/* ---------- Поиск поставщика ---------- */
ROUTES.search = () => {
  const q = UI.lastQuery, res = UI.lastResults;
  // До первого поиска: крупная строка запроса и примеры
  if (!q) return `<div class="wrap page">${crumbs(["#search", "Поиск поставщика"])}
    <div class="s-intro">
      <h1 class="h1">Поиск поставщика</h1>
      <p class="lead">Опишите потребность своими словами. Система разберёт запрос на параметры и подберёт предприятия только из проверенной базы.</p>
      ${searchForm("")}
      <div class="qchips">${HOME_EXAMPLES.map(([t, x]) => `<button type="button" data-example="${esc(x)}">${esc(t)}</button>`).join("")}</div>
    </div></div>`;
  const list = filterSearch(res);
  return `<div class="wrap page">${crumbs(["#search", "Поиск поставщика"])}
  <div class="s-layout">
    <div class="s-main">
      ${searchForm(q.raw)}
      <div class="s-head"><h1 class="h1">Результаты поиска</h1><span class="s-count">${list.length} ${plural(list.length, "предприятие", "предприятия", "предприятий")}</span></div>
      <div class="s-bar">
        <label class="chk"><input type="checkbox" id="show-unv" ${App.showUnverified ? "checked" : ""}> Показывать неподтверждённые</label>
        <div class="s-tools">
          <label class="s-sort">Сортировать по:
            <select data-sort="search" aria-label="Сортировка">${[["match", "соответствию"], ["risk", "уровню риска"], ["distance", "расстоянию"], ["data", "полноте данных"], ["name", "названию"]].map(([v, t]) => `<option value="${v}" ${(UI.searchSort || "match") === v ? "selected" : ""}>${t}</option>`).join("")}</select>
          </label>
          <button class="icon-btn sm" data-act="save-search" title="Сохранить поиск" aria-label="Сохранить поиск"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M6 3h12v18l-6-4-6 4z"/></svg></button>
          ${list.length > 1 ? `<button class="icon-btn sm" data-act="compare-results" title="Сравнить найденных" aria-label="Сравнить найденных"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h13l-3-3M20 17H7l3 3"/></svg></button>` : ""}
        </div>
      </div>
      ${list.length ? sortSearch(list).map(resultCard).join("") : `<div class="s-empty"><b>Ничего не найдено</b><p>В собранных открытых источниках нет подходящих предприятий${res.length ? " с выбранными фильтрами" : ""}. Уточните запрос, снимите фильтры или создайте заявку: её увидят предприятия, которые подключатся к платформе.</p><a class="btn pri" href="#buy.new">Создать заявку</a></div>`}
    </div>
    ${searchSidebar(q, res)}
  </div></div>`;
};
// Строка поиска (общая для пустого состояния и результатов)
function searchForm(v) {
  return `<form class="search lg" id="main-search" role="search">
    <label class="sr" for="sq">Потребность</label>
    <span class="search-ic" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/></svg></span>
    <input id="sq" name="q" value="${esc(v)}" placeholder="Что нужно найти? Например, круг из стали 40Х, 500 т в месяц" autocomplete="off">
    ${App.sample ? `<button class="btn txt" type="button" data-act="ai-parse" title="Разобрать запрос с помощью AI">AI</button>` : ""}
    <button class="search-go" type="submit">Найти<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
  </form>`;
}
// Параметры запроса по-русски для боковой панели
function queryParams(q) {
  const out = [];
  q.products.forEach((p) => out.push(["Продукция", p.label]));
  q.technologies.forEach((p) => out.push(["Технология", p.label]));
  if (q.industry) out.push(["Отрасль", q.industry.label]);
  if (q.material) out.push(["Материал", q.material.label]);
  q.grades.forEach((g) => out.push(["Марка", g]));
  if (q.volume != null) out.push(["Объём", q.volume + " " + (q.unit || "") + (q.period ? "/" + q.period : "")]);
  if (q.regionName) out.push(["Регион", q.regionName]);
  if (q.okpd2) out.push(["ОКПД2", q.okpd2]);
  if (q.okved) out.push(["ОКВЭД", q.okved]);
  return out;
}
// Боковая панель «Параметры поиска»: распознанный запрос и фильтры
function searchSidebar(q, res) {
  const f = UI.sf;
  const cities = [...new Set(res.map((m) => m.c.city))];
  const params = queryParams(q);
  return `<aside class="s-side" aria-label="Параметры поиска">
    <h2 class="s-side-h">Параметры поиска</h2>
    <section><h3>Распознано из запроса</h3>
      ${params.length ? `<dl class="s-params">${params.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : `<p class="muted">Параметры не распознаны, поиск по словам запроса.</p>`}
      ${q.missing.length ? `<p class="s-miss">Не указано: ${q.missing.map((m) => esc(m.t)).join(", ")}</p>` : ""}
      <a class="s-link" href="#buy.new">Создать заявку из запроса →</a>
    </section>
    <section><h3>Статус проверки</h3>
      ${[["VERIFIED", "Подтверждено"], ["PARTIALLY_VERIFIED", "Частично подтверждено"]].map(([k, t]) => `<label class="chk"><input type="checkbox" data-sf-hide="${k}" ${!f.hide.includes(k) ? "checked" : ""}> ${t}</label>`).join("")}
    </section>
    <section><h3>Риски</h3>
      <label class="chk"><input type="checkbox" data-sf="noRisk" ${f.noRisk ? "checked" : ""}> Без критичных рисков и расхождений</label>
      <label class="chk"><input type="checkbox" data-sf="site" ${f.site ? "checked" : ""}> С подтверждённым сайтом</label>
    </section>
    ${cities.length > 1 ? `<section><h3>Город</h3>${cities.map((x) => `<label class="chk"><input type="checkbox" data-sf-city="${esc(x)}" ${!f.cities.includes(x) ? "checked" : ""}> ${esc(x)}</label>`).join("")}</section>` : ""}
    <button class="btn sm" data-act="reset-sf">Сбросить фильтры</button>
  </aside>`;
}
// Фильтры боковой панели поиска
function filterSearch(res) {
  const f = UI.sf;
  return res.filter((m) => {
    if (f.hide.includes(m.c.verification_status)) return false;
    if (f.cities.includes(m.c.city)) return false;
    if (f.noRisk && companyRisks(m.c).risks.some((x) => x.level !== "low")) return false;
    if (f.site && !m.c.sources.some((s) => s.source_type === "OFFICIAL_SITE" && s.fetch_status === "OK")) return false;
    return true;
  });
}
// Сортировка результатов поиска
function sortSearch(res) {
  const s = UI.searchSort || "match";
  const rk = { none: 0, low: 1, mid: 2, high: 3 };
  const f = { match: (a, b) => b.yes - a.yes || a.applicable - b.applicable, risk: (a, b) => rk[companyRisks(a.c).level] - rk[companyRisks(b.c).level], distance: (a, b) => (a.dist ?? 1e9) - (b.dist ?? 1e9), data: (a, b) => completeness(b.c).n - completeness(a.c).n, name: (a, b) => a.c.short.localeCompare(b.c.short, "ru") }[s];
  return res.slice().sort(f);
}
// Карточка найденного предприятия: слева кто и что, справа соответствие, реквизиты и риски
function resultCard(m) {
  const c = m.c, cmpd = App.profile.compare.includes("c:" + c.id);
  const age = yearsSince(c.reg_date);
  const pct = m.applicable ? m.yes / m.applicable : 0;
  return `<article class="res">
    <div class="res-main">
      <div class="res-top"><span class="res-kind">${c.okved_main ? "ОКВЭД " + esc(c.okved_main) + " · " : ""}${esc(c.subindustry)}</span>
        <span class="res-acts">
          <button class="icon-btn sm ${cmpd ? "on" : ""}" data-cmp="c:${esc(c.id)}" title="${cmpd ? "Убрать из сравнения" : "Сравнить"}" aria-label="Сравнить"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h13l-3-3M20 17H7l3 3"/></svg></button>
          <button class="icon-btn sm" data-act="to-chain" data-company="${esc(c.id)}" title="В производственную цепочку" aria-label="В производственную цепочку"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="2" y="9" width="6" height="6"/><rect x="16" y="9" width="6" height="6"/><path d="M8 12h8"/></svg></button>
        </span></div>
      <div class="res-title"><a href="#c.${esc(c.id)}">${esc(c.name)}</a>${statusBadge(c.verification_status)}</div>
      <div class="res-f"><span>Подходящая продукция</span><p>${m.prods.length ? m.prods.slice(0, 3).map((p) => `<a href="#p.${esc(p.id)}">${esc(p.name)}</a>`).join(", ") + (m.prods.length > 3 ? ` и ещё ${m.prods.length - 3}` : "") : esc(c.subindustry)}</p></div>
      <div class="res-f"><span>Адрес</span><p>${esc(c.address || c.city)}${m.dist != null ? ` <span class="muted">· ${esc(distTxt(m.dist, App.profile.city))}</span>` : ""}</p></div>
      <details class="res-why"><summary>Почему предприятие в результатах</summary><div>${matchTable(m)}</div></details>
    </div>
    <div class="res-side">
      <span class="res-lbl">Соответствие запросу</span>
      <div class="res-score ${pct >= .6 ? "hi" : pct >= .3 ? "md" : "lo"}"><b class="num">${m.yes} из ${m.applicable}</b><span>критериев</span></div>
      <div class="res-grid">
        <div><span class="res-lbl">ИНН</span><span class="num">${c.inn ? esc(c.inn) : "не найден"}</span></div>
        <div><span class="res-lbl">На рынке</span><span>${age != null ? `${age} ${plural(age, "год", "года", "лет")}` : "нет данных"}</span></div>
      </div>
      <span class="res-lbl">Риски</span>${riskBadge(c)}
      ${isMine(c.id) ? `<span class="muted res-cta">Это ваша компания</span>` : `<button class="btn sm pri res-cta" data-act="rfq" data-company="${esc(c.id)}">Запросить предложение</button>`}
    </div>
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
  UI.lastQuery = q; UI.sf.cities = [];
  UI.lastResults = searchCompanies(q, { includeUnverified: App.showUnverified });
  if (location.hash !== "#search") location.hash = "#search"; else render();
}

/* ---------- Рынок сбыта ---------- */
function offerRow(o) {
  return `<article class="card flat" style="margin-bottom:8px"><div class="card-head"><div style="min-width:0"><span class="label">${esc(o.kind_label || "Предложение")}</span><h3 class="h3" style="font-size:16px">${esc(o.title)}</h3>
    <div class="muted">${esc(o.company_name || "Предприятие не указано")} · ${esc(o.city || "")} · ${fmtDate(o.created_at)}</div></div>${itemTag("offers", o)}</div>${rejectNote("offers", o)}
    <div class="row" style="margin-top:8px">${o.okpd2 ? okpdTag({ code: o.okpd2, name: App.data.okpd2[o.okpd2] || "", status: "USER" }) : ""}<span>${priceHtml(o.price)}</span>${o.qty ? `<span class="muted">Объём: ${esc(o.qty)} ${esc(o.unit || "")}</span>` : ""}</div>
    <div class="row" style="margin-top:8px"><button class="btn sm" data-act="offer-open" data-id="${esc(o.id)}">Подробнее</button>${o.author === App.uid ? `<button class="btn sm txt" data-act="offer-del" data-id="${esc(o.id)}">Снять с публикации</button>` : isMine(o.company_id) ? "" : `<button class="btn sm" data-act="rfq-offer" data-id="${esc(o.id)}">Запросить предложение</button>`}</div></article>`;
}
// Продукция и услуги предприятий, собранные из открытых источников, в виде предложений поставщиков
function baseOffers() {
  return allProducts().map((p) => ({ base: true, id: "p:" + p.id, p, company_id: p.company_id, title: p.name,
    kind_label: p.kind === "service" ? "Производственные услуги" : "Продукция" }));
}
// Все предложения рынка: размещённые пользователями (новые первыми), затем продукция из открытых источников.
// Позиции предприятий самого пользователя здесь не показываются — они в кабинете, во вкладке «Мои предложения»
function marketOffers({ kind = "", q = "" } = {}) {
  const mine = myCompanyIds(), s = q.trim().toLowerCase();
  const user = shownToAll("offers").sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
  return [...user, ...baseOffers()].filter((o) => !mine.has(o.company_id) && (!kind || o.kind_label === kind)
    && (!s || [o.title, o.company_name, o.p?.c.name, o.p?.category, o.p?.okpd2?.code, o.okpd2].join(" ").toLowerCase().includes(s)));
}
// Действия с позицией из открытых источников: чужую можно запросить, свою — изменить и удалить (подтверждённому представителю)
function productActions(p, cls = "btn sm") {
  const cid = p.company_id || p.c?.id;
  if (canEditProducts(cid)) return `<button class="${cls}" data-act="prod-edit" data-product="${esc(p.id)}">Изменить</button><button class="${cls} danger" data-act="prod-del" data-product="${esc(p.id)}">Удалить</button>`;
  if (isMine(cid)) return `<span class="muted">Изменять позиции можно после подтверждения модератором</span>`;
  return `<button class="${cls}${cls === "btn" ? " pri" : ""}" data-act="rfq" data-product="${esc(p.id)}">Запросить предложение</button>`;
}
// Пометка позиции: изменена представителем компании или взята из открытых источников
const productTag = (p) => p.company_edit
  ? `<span class="st VERIFIED" title="Позицию изменил подтверждённый представитель компании ${fmtDate(p.company_edit.at)}">Изменено представителем компании</span>`
  : `<span class="st PARTIALLY_VERIFIED" title="Позиция найдена на сайте предприятия или в каталоге; условия поставки уточняются у предприятия">Из открытых источников</span>`;
// Строка предложения из открытых источников: ведёт на карточку продукции, цена — по запросу
function baseOfferRow(x) {
  const p = x.p, c = p.c;
  return `<article class="card flat" style="margin-bottom:8px"><div class="card-head"><div style="min-width:0"><span class="label">${esc(x.kind_label)} · ${esc(p.category)}</span><h3 class="h3" style="font-size:16px"><a href="#p.${esc(p.id)}">${esc(p.name)}</a></h3>
    <div class="muted"><a href="#c.${esc(c.id)}">${esc(c.name)}</a> · ${esc(c.city || regionName(c.region))}</div></div>${productTag(p)}</div>
    <div class="row" style="margin-top:8px">${okpdTag(p.okpd2)}<span>${unk("price")}</span></div>
    <div class="row" style="margin-top:8px"><a class="btn sm" href="#p.${esc(p.id)}">Подробнее</a>${productActions(p)}${srcBtn(p.source_id)}</div></article>`;
}
const marketRow = (x) => (x.base ? baseOfferRow(x) : offerRow(x));
// Фильтр по категориям в виде чипсов со счётчиком, как на маркетплейсах.
// Пустые категории не показываются (кроме выбранной), счётчики учитывают строку поиска
function categoryChips(cats, cur) {
  const all = marketOffers({ q: UI.sell.q });
  const n = (c) => (c ? all.filter((o) => o.kind_label === c).length : all.length);
  // id по номеру категории: после перерисовки фокус клавиатуры возвращается на ту же кнопку
  const chip = (c) => `<button type="button" class="chip-f" id="sellf-${["", ...cats].indexOf(c)}" aria-pressed="${cur === c}" data-sellf="${esc(c)}">${esc(c || "Все")}<span class="n">${n(c)}</span></button>`;
  return `<div class="chips-scroll"><div class="chip-row" role="group" aria-label="Категории предложений"><span class="chips-fade l" aria-hidden="true"></span>${["", ...cats].filter((c) => !c || c === cur || n(c)).map(chip).join("")}<span class="chips-fade r" aria-hidden="true"></span></div></div>`;
}
// Страница рынка сбыта (предложения поставщиков)
ROUTES.sell = () => {
  const cats = ["Продукция", "Материалы", "Комплектующие", "Оборудование", "Производственные услуги", "Технологии", "Производственные мощности", "Свободные мощности", "Складские остатки"];
  const f = UI.sellFilter || "";
  const list = marketOffers({ kind: f, q: UI.sell.q });
  const hidden = loggedIn() ? [...App.offers, ...baseOffers()].filter((o) => myCompanyIds().has(o.company_id)).length : 0;
  const pg = list.slice((UI.sell.page - 1) * PAGE_SIZE, UI.sell.page * PAGE_SIZE);
  return `<div class="wrap page">${crumbs(["#sell", "Рынок сбыта"])}
  <div class="sec-h"><div><div class="label">Продать</div><h1 class="h1">Предложения поставщиков</h1></div><button class="btn pri" data-act="offer-new">Разместить предложение</button></div>
  <p class="muted" style="max-width:760px">Продукция, материалы, услуги и свободные мощности предприятий. Позиции «Из открытых источников» собраны с сайтов предприятий и из каталогов: цену и сроки уточняйте запросом. Предложения пользователей помечены «Указано пользователем», пока модератор не подтвердит представителя компании.</p>
  ${categoryChips(cats, f)}
  <div class="toolbar"><div class="search" style="flex:1;min-width:240px"><label class="sr" for="sellq">Поиск предложений</label><input id="sellq" data-q="sell" value="${esc(UI.sell.q)}" placeholder="Название, предприятие, код ОКПД2"></div></div>
  <p class="muted" style="margin:0 0 12px">Найдено: ${list.length}${hidden ? ` · позиции вашей компании (${hidden}) здесь не показываются, они в <a href="#cabinet.offers">личном кабинете</a>` : ""}</p>
  ${pg.length ? pg.map(marketRow).join("") : `<div class="note">В этой категории предложений нет.</div>`}
  ${pager("sell", list.length)}
  </div>`;
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
  ${itemTag("offers", o)}${rejectNote("offers", o)}
  <dl class="kv" style="margin-top:16px">
    <dt>Предприятие</dt><dd>${esc(o.company_name)}${o.company_id ? ` · <a href="#c.${esc(o.company_id)}" data-close>карточка</a>` : ""}</dd>
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
    <dt>Модерация</dt><dd>${modStatusTxt("offers", o)}</dd>
  </dl>
  <div class="row" style="margin-top:16px">${isMine(o.company_id, o.author) ? "" : `<button class="btn pri" data-act="rfq-offer" data-id="${esc(o.id)}">Запросить предложение</button>`}${o.author === App.uid ? `<button class="btn danger" data-act="offer-del" data-id="${esc(o.id)}">Снять с публикации</button>` : ""}</div>`);
}

/* ---------- Рынок приобретения ---------- */
function requestRow(r) {
  return `<article class="card flat" style="margin-bottom:8px"><div class="card-head"><div style="min-width:0"><span class="label">Заявка${r.target_company ? " предприятию" : ""}</span><h3 class="h3" style="font-size:16px"><a href="#r.${esc(r.id)}">${esc(r.what)}</a></h3>
    <div class="muted">${r.qty ? esc(r.qty + " " + (r.unit || "") + (r.period ? "/" + r.period : "")) + " · " : ""}${esc(r.region_name || "Регион не указан")} · ${fmtDate(r.created_at)}</div></div>${itemTag("requests", r)}</div>${rejectNote("requests", r)}
    <div class="row" style="margin-top:8px"><a class="btn sm" href="#r.${esc(r.id)}">Открыть заявку</a><span class="muted">Откликов: ${responsesOf(r).length}</span></div></article>`;
}
// Страница рынка приобретения (заявки покупателей)
ROUTES.buy = () => {
  const reqs = shownToAll("requests").sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
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
  const r = shownToAll("requests").find((x) => x.id === id);
  if (!r) return `<div class="wrap page">${crumbs(["#buy", "Рынок приобретения"], ["", "Заявка"])}<div class="note">Заявка не найдена или ещё загружается.</div></div>`;
  const q = requestQuery(r);
  let res = searchCompanies(q, { includeUnverified: App.showUnverified, city: r.city });
  if (r.max_distance) res = res.filter((m) => m.dist == null || m.dist <= Number(r.max_distance));
  const mine = r.author === App.uid;
  return `<div class="wrap page">${crumbs(["#buy", "Рынок приобретения"], ["", "Заявка"])}
  <div class="card-head"><div><div class="label">Заявка${r.target_company ? " · адресована: " + esc(App.C[r.target_company]?.short || "") : ""}</div><h1 class="h1">${esc(r.what)}</h1><div class="muted">Создана ${fmtDate(r.created_at)}</div></div>${itemTag("requests", r)}</div>${rejectNote("requests", r)}
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
    <div><h2 class="h2" style="margin-bottom:8px">Отклики (${responsesOf(r).length})</h2>
      ${responsesOf(r).map((x) => `<div class="card flat" style="margin-bottom:8px"><b>${esc(x.company)}</b> <span class="muted">${fmtDate(x.at)}</span><div>${esc(x.text)}</div>${x.price ? `<div>${priceHtml({ value: x.price, unit: r.unit })}</div>` : ""}</div>`).join("") || '<div class="note">Откликов пока нет.</div>'}
      ${r.author === App.uid ? `<p class="muted" style="margin-top:12px">Это ваша заявка: отклики поставщиков появятся здесь и во вкладке «Сообщения» личного кабинета.</p>` : `<form id="respond-form" data-id="${esc(r.id)}" class="stack" style="margin-top:12px"><div class="label">Откликнуться на заявку</div>
        <input class="inp" name="company" required placeholder="Ваше предприятие" aria-label="Предприятие" list="of-cos2"><datalist id="of-cos2">${App.data.companies.map((c) => `<option value="${esc(c.name)}">`).join("")}</datalist>
        <textarea class="inp" name="text" required placeholder="Условия, сроки, документы" aria-label="Текст отклика"></textarea>
        <input class="inp" name="price" inputmode="decimal" placeholder="Цена за единицу, ₽ (необязательно)" aria-label="Цена">
        <button class="btn pri" type="submit">Отправить отклик</button></form>`}
      ${mine ? `<div class="row" style="margin-top:12px"><button class="btn danger sm" data-act="request-del" data-id="${esc(r.id)}">Закрыть заявку</button></div>` : ""}
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
    ["Позиция", (x) => x.p ? `<a href="#p.${esc(x.p.id)}">${esc(x.p.name)}</a>` : `<span class="muted">Предприятие целиком</span>`],
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
  <div class="tbl-wrap"><table class="tbl sticky"><thead><tr><th>Параметр</th>${items.map((x) => `<th style="min-width:220px;white-space:normal"><a href="#c.${esc(x.c.id)}">${esc(x.c.short)}</a><br><button class="btn sm txt" data-cmp="${x.k}">Убрать</button></th>`).join("")}</tr></thead>
  <tbody>${rows.map(([n, f]) => `<tr><td><b>${esc(n)}</b></td>${items.map((x) => `<td>${f(x)}</td>`).join("")}</tr>`).join("")}</tbody></table></div></div>`;
};
