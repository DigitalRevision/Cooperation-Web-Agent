/* ===== Роутер и страницы каталога ===== */
const ROUTES = {};
const UI = { companies: { page: 1, sort: "status", q: "", f: {} }, products: { page: 1, sort: "name", q: "", f: {} }, lastQuery: null, lastResults: null, cabinetTab: "offers", adminTab: "companies" };
const PAGE_SIZE = 10;

function route() {
  const h = (location.hash || "#home").slice(1);
  const [name, ...rest] = h.split(".");
  return { name: name || "home", arg: rest.join(".") };
}
let _rr = 0;
function rerender() { cancelAnimationFrame(_rr); _rr = requestAnimationFrame(render); }
function render() {
  if (!App.data) return;
  const r = route();
  const fn = ROUTES[r.name] || ROUTES.home;
  const main = $("#app");
  const keepFocus = document.activeElement?.id;
  const selStart = document.activeElement?.selectionStart;
  main.innerHTML = fn(r.arg);
  $$(".nav a,.bnav a,.drawer a").forEach((a) => a.setAttribute("aria-current", a.getAttribute("href") === "#" + (NAV_OF[r.name] || r.name) ? "page" : "false"));
  $("#mkt-strip").hidden = !["home", "buy", "sell", "search", "companies", "products", "r"].includes(r.name);
  $$("#mkt-strip .mkt a").forEach((a) => a.setAttribute("aria-current", a.dataset.m === (r.name === "sell" ? "sell" : r.name === "buy" || r.name === "r" ? "buy" : "") ? "true" : "false"));
  if (keepFocus && $("#" + keepFocus)) { const el = $("#" + keepFocus); el.focus(); try { if (selStart != null) el.setSelectionRange(selStart, selStart); } catch (e) {} }
  document.title = "Промышленная кооперация";
}
const NAV_OF = { c: "companies", p: "products", r: "buy", ch: "chains", compare: "companies" };
window.addEventListener("hashchange", () => { closePanel(); $("#drawer")?.classList.remove("open"); render(); window.scrollTo(0, 0); });

const crumbs = (...items) => `<nav class="crumbs" aria-label="Путь">${[["#home", "Главная"], ...items].map(([h, t], i, a) => i < a.length - 1 ? `<a href="${h}">${esc(t)}</a> / ` : esc(t)).join("")}</nav>`;
const pager = (key, total) => {
  const pages = Math.ceil(total / PAGE_SIZE); if (pages <= 1) return "";
  const cur = UI[key].page;
  return `<nav class="pager" aria-label="Страницы">${Array.from({ length: pages }, (_, i) => `<button class="btn sm ${i + 1 === cur ? "pri" : ""}" data-page="${key}:${i + 1}" aria-label="Страница ${i + 1}">${i + 1}</button>`).join("")}</nav>`;
};

/* ---------- Главная ---------- */
ROUTES.home = () => {
  const cs = App.data.companies, vol = cs.filter((c) => c.region === "34");
  const shown = vol.filter((c) => c.verification_status !== "OUTDATED" && c.verification_status !== "UNVERIFIED").length;
  const prods = vol.reduce((n, c) => n + c.products.length, 0);
  const srcs = vol.reduce((n, c) => n + c.sources.length, 0);
  const recentReq = App.requests.slice().sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")).slice(0, 3);
  const recentOff = App.offers.slice().sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")).slice(0, 3);
  return `
  <section class="hero"><div class="wrap">
    <div>
      <h1 class="display">Промышленная кооперация</h1>
      <p class="lead">Находите производителей, поставщиков и производственные возможности. Каждое значение — с источником и датой проверки.</p>
      <form class="search" id="home-search" role="search">
        <label class="sr" for="hq">Что нужно найти</label>
        <input id="hq" name="q" placeholder="Например: нужна стальная заготовка 500 тонн в месяц в Волгоградской области" autocomplete="off">
        <button class="btn pri" type="submit">Найти</button>
      </form>
      <div class="ex"><span class="muted">Примеры:</span>
        ${["Нужна трубная заготовка из стали 40Х, 500 тонн в месяц, Волгоградская область", "Нужен производитель деталей для нефтегазового оборудования", "Термообработка длинномерных деталей до 6 м", "Кран козловой 20 т"].map((x) => `<button data-example="${esc(x)}">${esc(x)}</button>`).join("")}
      </div>
    </div>
    ${heroArt()}
  </div></section>
  <div class="wrap">
    <section class="sec">
      <div class="sec-h"><h2 class="h2">Что вы хотите сделать</h2></div>
      <div class="actions">
        <a class="act" href="#companies"><b>Найти предприятие</b><span>Каталог с ОКВЭД, адресами и источниками</span></a>
        <a class="act" href="#products"><b>Найти продукцию</b><span>Продукция и услуги с ОКПД2 и параметрами</span></a>
        <a class="act" href="#search"><b>Найти поставщика</b><span>Опишите потребность — система объяснит совпадения</span></a>
        <a class="act" href="#sell.new"><b>Разместить продукцию</b><span>Рынок сбыта: продукция, мощности, услуги</span></a>
        <a class="act" href="#buy.new"><b>Создать заявку</b><span>Рынок приобретения: потребности и требования</span></a>
        <a class="act" href="#chains"><b>Построить цепочку</b><span>Этапы, поставщики, замена поставщика</span></a>
      </div>
    </section>
  </div>
  <section class="band sec"><div class="wrap">
    <div class="sec-h"><div><div class="label">Пилотный регион</div><h2 class="h2">Волгоградская область</h2></div><a class="btn" href="#companies">Все предприятия региона</a></div>
    <div class="grid3" style="margin-bottom:24px">
      <div class="stat"><b class="num">${vol.length}</b><span class="muted">предприятий в базе, из них ${shown} в основном поиске (подтверждённые и частично подтверждённые)</span></div>
      <div class="stat"><b class="num">${prods}</b><span class="muted">позиций продукции и услуг, у каждой — источник</span></div>
      <div class="stat"><b class="num">${srcs}</b><span class="muted">источников: официальные сайты, сведения ЕГРЮЛ, каталоги. Проверено ${fmtDate(App.data.generated_at)}</span></div>
    </div>
    <div class="grid3">${vol.filter((c) => c.verification_status !== "OUTDATED").slice(0, 6).map(companyMini).join("")}</div>
    <p class="muted" style="margin-top:16px">Далее: Ростовская, Астраханская, Саратовская, Воронежская, Самарская области, Москва и Московская область, Санкт-Петербург и Ленинградская область.</p>
  </div></section>
  <div class="wrap">
    <section class="sec">
      <div class="sec-h"><h2 class="h2">Путь к кооперации</h2></div>
      <div class="flow"><span>Поиск</span><i>→</i><span>Предприятие</span><i>→</i><span>Продукция</span><i>→</i><span>Предложение</span><i>→</i><span>Заявка</span><i>→</i><span>Производственная цепочка</span></div>
    </section>
    <section class="sec grid2">
      <div><div class="sec-h"><h2 class="h2">Новые заявки</h2><a href="#buy">Рынок приобретения</a></div>
        ${recentReq.length ? recentReq.map(requestRow).join("") : `<div class="note">Заявок пока нет. <a href="#buy.new">Создать первую заявку</a></div>`}</div>
      <div><div class="sec-h"><h2 class="h2">Новые предложения</h2><a href="#sell">Рынок сбыта</a></div>
        ${recentOff.length ? recentOff.map(offerRow).join("") : `<div class="note">Предложений от пользователей пока нет. <a href="#sell.new">Разместить предложение</a></div>`}</div>
    </section>
  </div>`;
};
function heroArt() {
  // Узор «производственная цепочка» — узлы и связи, в духе схем на главной soyuzmash.ru
  return `<svg viewBox="0 0 420 300" aria-hidden="true">
    <rect x="40" y="30" width="120" height="180" rx="3" fill="#005ca8"/>
    <rect x="190" y="0" width="150" height="230" rx="3" fill="#094d85"/>
    <rect x="40" y="226" width="80" height="24" rx="3" fill="#2388ed"/>
    <rect x="0" y="150" width="30" height="100" rx="3" fill="#eef5fd" stroke="#d9dde2"/>
    <g fill="none" stroke="#2388ed" stroke-width="2"><path d="M14 190 H380"/><path d="M270 190 V90 H400" /><path d="M100 190 V270 H300" stroke-dasharray="6 4"/></g>
    <g fill="#fff" stroke="#2388ed" stroke-width="2">${[14, 60, 100, 150, 220, 270, 320].map((x) => `<rect x="${x - 8}" y="182" width="16" height="16" rx="3"/>`).join("")}<rect x="392" y="82" width="16" height="16" rx="3"/><rect x="292" y="262" width="16" height="16" rx="3"/></g>
    <rect x="372" y="182" width="16" height="16" rx="3" fill="#094d85"/>
  </svg>`;
}
function companyMini(c) {
  const cmp = completeness(c);
  return `<article class="card"><div class="card-head"><h3 class="h3"><a href="#c.${c.id}">${esc(c.name)}</a></h3>${statusBadge(c.verification_status)}</div>
  <div class="muted" style="margin-top:4px">${esc(c.city)} · ${esc(c.subindustry)}</div>
  <div class="row" style="margin-top:8px">${okvedTag(c.okved_main)}<span class="muted">${c.products.length} ${plural(c.products.length, "позиция", "позиции", "позиций")} · заполнено ${cmp.n} из ${cmp.of} полей</span></div></article>`;
}

/* ---------- Каталог предприятий ---------- */
function companyFilters(list) {
  const f = UI.companies.f;
  const ind = [...new Set(App.data.companies.map((c) => c.industry))];
  const cities = [...new Set(App.data.companies.map((c) => c.city))];
  const okv = [...new Set(App.data.companies.map((c) => c.okved_main).filter(Boolean))].sort();
  const techs = [...new Set(App.data.companies.flatMap((c) => c.technologies.map((t) => t.name)))];
  const opt = (arr, v) => `<option value="">Любой</option>` + arr.map((x) => `<option ${v === x ? "selected" : ""}>${esc(x)}</option>`).join("");
  return `<aside class="filters" id="filters" aria-label="Фильтры">
    <div class="row" style="justify-content:space-between;margin-bottom:12px"><span class="label">Фильтры</span><button class="btn sm filters-toggle" data-act="filters-close">Показать ${list.length}</button></div>
    <fieldset><legend class="label">Регион и город</legend>
      <select class="sel" data-f="companies:region"><option value="">Все регионы</option>${Object.values(App.data.regions).map((r) => `<option value="${r.code}" ${f.region === r.code ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select>
      <select class="sel" style="margin-top:8px" data-f="companies:city"><option value="">Любой город</option>${cities.map((x) => `<option ${f.city === x ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
      <label class="field" style="margin-top:8px"><span class="label">Расстояние от г. ${esc(App.profile.city)}, км</span><select class="sel" data-f="companies:dist"><option value="">Любое</option>${[50, 200, 400].map((d) => `<option value="${d}" ${String(f.dist) === String(d) ? "selected" : ""}>до ${d}</option>`).join("")}</select></label>
    </fieldset>
    <fieldset><legend class="label">Статус проверки</legend>
      <label class="chk"><input type="checkbox" data-fs="VERIFIED" ${!(f.hide || []).includes("VERIFIED") ? "checked" : ""}> ✓ Подтверждено</label>
      <label class="chk"><input type="checkbox" data-fs="PARTIALLY_VERIFIED" ${!(f.hide || []).includes("PARTIALLY_VERIFIED") ? "checked" : ""}> ◐ Частично подтверждено</label>
      <label class="chk"><input type="checkbox" id="show-unv" ${App.showUnverified ? "checked" : ""}> Показывать неподтверждённые и устаревшие данные</label>
    </fieldset>
    <fieldset><legend class="label">Отрасль</legend><select class="sel" data-f="companies:industry">${opt(ind, f.industry)}</select></fieldset>
    <fieldset><legend class="label">ОКВЭД (основной)</legend><select class="sel" data-f="companies:okved">${`<option value="">Любой</option>` + okv.map((x) => `<option value="${x}" ${f.okved === x ? "selected" : ""}>${x} — ${esc(App.data.okved[x].slice(0, 50))}</option>`).join("")}</select></fieldset>
    <fieldset><legend class="label">Технология</legend><select class="sel" data-f="companies:tech">${opt(techs, f.tech)}</select></fieldset>
    <fieldset><legend class="label">Опубликовано</legend>
      <label class="chk"><input type="checkbox" data-fb="capacities" ${f.capacities ? "checked" : ""}> Производственная мощность</label>
      <label class="chk"><input type="checkbox" data-fb="certificates" ${f.certificates ? "checked" : ""}> Сертификаты</label>
      <label class="chk"><input type="checkbox" data-fb="discrepancies" ${f.discrepancies ? "checked" : ""}> Есть расхождения источников</label>
    </fieldset>
    <button class="btn sm" data-act="reset-companies">Сбросить фильтры</button>
  </aside>`;
}
function filterCompanies() {
  const { f, q, sort } = UI.companies;
  let list = App.data.companies.filter((c) => {
    const st = c.verification_status;
    if (!App.showUnverified && (st === "UNVERIFIED" || st === "OUTDATED")) return false;
    if ((f.hide || []).includes(st)) return false;
    if (f.region && c.region !== f.region) return false;
    if (f.city && c.city !== f.city) return false;
    if (f.dist) { const d = distanceKm(App.profile.city, c.city); if (d == null || d > Number(f.dist)) return false; }
    if (f.industry && c.industry !== f.industry) return false;
    if (f.okved && c.okved_main !== f.okved) return false;
    if (f.tech && !c.technologies.some((t) => t.name === f.tech)) return false;
    if (f.capacities && !c.capacities.length) return false;
    if (f.certificates && !c.certificates.length) return false;
    if (f.discrepancies && !(c.discrepancies || []).length) return false;
    if (q) { const s = q.toLowerCase(); const hay = [c.name, c.legal_name, c.inn, c.ogrn, c.city, c.subindustry, c.okved_main, ...c.products.map((p) => p.name)].join(" ").toLowerCase(); if (!hay.includes(s)) return false; }
    return true;
  });
  const ord = { VERIFIED: 0, PARTIALLY_VERIFIED: 1, UNVERIFIED: 2, OUTDATED: 3 };
  const sorters = {
    status: (a, b) => (App.data.regions[b.region]?.pilot ? 1 : 0) - (App.data.regions[a.region]?.pilot ? 1 : 0) || ord[a.verification_status] - ord[b.verification_status] || a.short.localeCompare(b.short, "ru"),
    name: (a, b) => a.short.localeCompare(b.short, "ru"),
    completeness: (a, b) => completeness(b).n - completeness(a).n,
    distance: (a, b) => (distanceKm(App.profile.city, a.city) ?? 1e9) - (distanceKm(App.profile.city, b.city) ?? 1e9),
    region: (a, b) => regionName(a.region).localeCompare(regionName(b.region), "ru") || a.city.localeCompare(b.city, "ru"),
    updated: (a, b) => (b.last_verified_at || TODAY).localeCompare(a.last_verified_at || TODAY),
    products: (a, b) => b.products.length - a.products.length,
  };
  return list.sort(sorters[sort] || sorters.status);
}
ROUTES.companies = () => {
  const list = filterCompanies();
  const pg = list.slice((UI.companies.page - 1) * PAGE_SIZE, UI.companies.page * PAGE_SIZE);
  return `<div class="wrap page">${crumbs(["#companies", "Каталог предприятий"])}
  <div class="sec-h"><h1 class="h1">Каталог предприятий</h1><a class="btn" href="#compare">Сравнение (${App.profile.compare.length})</a></div>
  <div class="cat">${companyFilters(list)}
  <div>
    <div class="toolbar">
      <div class="search" style="flex:1;min-width:240px"><label class="sr" for="cq">Поиск по названию, ИНН, продукции</label><input id="cq" data-q="companies" value="${esc(UI.companies.q)}" placeholder="Название, ИНН, ОГРН, продукция"></div>
      <button class="btn filters-toggle" data-act="filters-open">Фильтры</button>
      <label class="sr" for="csort">Сортировка</label>
      <select class="sel" id="csort" data-sort="companies">
        ${[["status", "По статусу проверки"], ["completeness", "По количеству подтверждённых данных"], ["distance", "По расстоянию от г. " + App.profile.city], ["region", "По региону"], ["name", "По названию"], ["products", "По числу позиций продукции"], ["updated", "По дате обновления"]].map(([v, t]) => `<option value="${v}" ${UI.companies.sort === v ? "selected" : ""}>${esc(t)}</option>`).join("")}
      </select>
    </div>
    <p class="muted" style="margin:0 0 12px">Найдено: ${list.length}. ${App.showUnverified ? "Показаны в том числе неподтверждённые и устаревшие записи." : "Показаны подтверждённые и частично подтверждённые записи."}</p>
    <div class="stack">${pg.map(companyCard).join("") || '<div class="note">Нет предприятий по выбранным фильтрам.</div>'}</div>
    ${pager("companies", list.length)}
  </div></div></div>`;
};
function companyCard(c) {
  const cmp = completeness(c);
  const d = distanceKm(App.profile.city, c.city);
  const fav = App.profile.favorites.includes("c:" + c.id), cmpd = App.profile.compare.includes("c:" + c.id);
  return `<article class="card">
    <div class="card-head"><div style="min-width:0"><h3 class="h3"><a href="#c.${c.id}">${esc(c.name)}</a></h3>
      <div class="muted" style="margin-top:2px">${esc(c.address || "Адрес не указан")}${d != null ? " · " + esc(distTxt(d, App.profile.city)) : ""}</div></div>
      ${statusBadge(c.verification_status)}</div>
    <div class="facts">
      <div><span class="label">ИНН</span>${c.inn ? `<span class="num">${esc(c.inn)}</span>` : unk("conf")}</div>
      <div><span class="label">Основной ОКВЭД</span>${okvedTag(c.okved_main)}</div>
      <div><span class="label">Отрасль</span>${esc(c.subindustry)}</div>
      <div><span class="label">Мощность</span>${c.capacities.filter((x) => !x.historical).map((x) => esc(x.text)).join("; ") || unk("none")}</div>
    </div>
    <div class="label">Что предприятие производит и продаёт</div>
    <div class="muted" style="margin-top:4px">${c.products.slice(0, 5).map((p) => `<a href="#p.${p.id}">${esc(p.name)}</a>`).join(" · ") || unk("none")}${c.products.length > 5 ? ` и ещё ${c.products.length - 5}` : ""}</div>
    <div class="row" style="margin-top:16px;justify-content:space-between">
      <div class="row"><a class="btn sm pri" href="#c.${c.id}">Карточка предприятия</a><button class="btn sm" data-cmp="c:${c.id}">${cmpd ? "Убрать из сравнения" : "Сравнить"}</button><button class="btn sm txt" data-fav="c:${c.id}">${fav ? "★ В избранном" : "☆ В избранное"}</button></div>
      <span class="muted">Заполнено ${cmp.n} из ${cmp.of} полей · проверено ${fmtDate(TODAY)}</span>
    </div>
  </article>`;
}

/* ---------- Карточка предприятия ---------- */
ROUTES.c = (id) => {
  const c = App.C[id]; if (!c) return notFound();
  const cmp = completeness(c);
  const egr = c.sources.find((s) => s.source_type === "EGRUL_AGGREGATOR")?.id;
  const site = c.sources.find((s) => s.source_type === "OFFICIAL_SITE")?.id || c.sources[0]?.id;
  const sells = c.products.filter((p) => p.kind === "product"), services = c.products.filter((p) => p.kind === "service");
  const rel = App.data.relations.filter((r) => r.from === id || r.to === id);
  const offers = App.offers.filter((o) => o.company_id === id), reqs = App.requests.filter((r) => r.company_id === id || r.target_company === id);
  const fav = App.profile.favorites.includes("c:" + id);
  return `<div class="wrap page">${crumbs(["#companies", "Каталог предприятий"], ["", c.short])}
  <div class="card-head"><div style="min-width:0">
    <h1 class="h1">${esc(c.name)}</h1>
    <div class="muted" style="margin-top:4px">${esc(c.legal_name || "Полное наименование не подтверждено")} ${srcBtn(egr, "ЕГРЮЛ")}</div>
  </div><div class="stack" style="align-items:flex-end">${statusBadge(c.verification_status)}<span class="muted">Проверено ${fmtDate(TODAY)}</span></div></div>
  ${c.discrepancies?.length ? `<div class="stack" style="margin-top:16px">${c.discrepancies.map((d) => `<div class="note warn"><b>${esc(d.field)}:</b> ${d.values.map((v) => `${esc(v.value)} ${srcBtn(v.source_id)}`).join(" · ")}${d.values.length ? "<br>" : ""}${esc(d.note)}</div>`).join("")}</div>` : ""}
  <div class="row" style="margin-top:16px">
    <button class="btn pri" data-act="rfq" data-company="${id}">Запросить предложение</button>
    <button class="btn" data-act="to-chain" data-company="${id}">Добавить в производственную цепочку</button>
    <button class="btn" data-cmp="c:${id}">Сравнить</button>
    <button class="btn txt" data-fav="c:${id}">${fav ? "★ В избранном" : "☆ В избранное"}</button>
    <button class="btn txt" data-act="report" data-company="${id}">Сообщить об ошибке в данных</button>
  </div>
  <div class="grid2 sec" style="margin-top:32px">
    <section><h2 class="h2" style="margin-bottom:12px">Реквизиты и контакты</h2>
      <dl class="kv">
        <dt>ИНН</dt><dd>${c.inn ? `<span class="num">${esc(c.inn)}</span> ${srcBtn(egr)}` : unk("conf")}</dd>
        <dt>ОГРН</dt><dd>${c.ogrn ? `<span class="num">${esc(c.ogrn)}</span> ${srcBtn(egr)}` : unk("conf")}</dd>
        <dt>КПП</dt><dd>${c.kpp ? `<span class="num">${esc(c.kpp)}</span>` : unk("na")}</dd>
        <dt>Регистрация</dt><dd>${c.reg_date ? fmtDate(c.reg_date) : unk("na")}</dd>
        <dt>Статус юрлица</dt><dd>${c.legal_status ? esc(c.legal_status) : unk("conf")}</dd>
        <dt>Регион, город</dt><dd>${esc(regionName(c.region))}, ${esc(c.city)}</dd>
        <dt>Адрес</dt><dd>${c.address ? esc(c.address) : unk("na")} ${srcBtn(site)}</dd>
        <dt>Сайт</dt><dd>${c.site ? `<a href="${esc(c.site)}" target="_blank" rel="noopener">${esc(domain(c.site))}</a>` : unk("none")}</dd>
        <dt>Телефон</dt><dd>${c.phones.length ? c.phones.map(esc).join("<br>") : unk("none")}</dd>
        <dt>E-mail</dt><dd>${c.emails.length ? c.emails.map(esc).join(", ") : unk("none")}</dd>
      </dl></section>
    <section><h2 class="h2" style="margin-bottom:12px">Деятельность</h2>
      <dl class="kv">
        <dt>Основной ОКВЭД</dt><dd>${okvedTag(c.okved_main, true)} ${srcBtn(egr)}</dd>
        <dt>Доп. ОКВЭД</dt><dd>${c.okved_extra?.length ? c.okved_extra.map((x) => okvedTag(x)).join(" ") : unk("none")}</dd>
        <dt>ОКПД2 продукции</dt><dd>${[...new Map(c.products.filter((p) => p.okpd2).map((p) => [p.okpd2.code, p.okpd2])).values()].map((o) => okpdTag(o)).join(" ") || unk("none")}</dd>
        <dt>Отрасль</dt><dd>${esc(c.industry)} · ${esc(c.subindustry)}</dd>
        <dt>Описание</dt><dd>${c.description ? esc(c.description) : unk("na")}</dd>
        <dt>Материалы</dt><dd>${c.materials.length ? c.materials.map((m) => esc(m.name)).join(", ") + " " + srcBtn(c.materials[0].source_id) : unk("none")}</dd>
        <dt>Технологии</dt><dd>${c.technologies.length ? c.technologies.map((t) => esc(t.name)).join("; ") + " " + srcBtn(c.technologies[0].source_id) : unk("none")}</dd>
        <dt>Производственные мощности</dt><dd>${c.capacities.length ? c.capacities.map((x) => `${esc(x.text)}${x.historical ? ' <span class="muted">(исторический показатель, не текущая мощность)</span>' : ""} ${srcBtn(x.source_id)}`).join("<br>") : unk("none")}</dd>
        <dt>Площадки и склады</dt><dd>${c.sites.length ? c.sites.map((s) => `${esc(s.name)}: ${esc(s.address)}${s.area ? ", площадь " + esc(s.area) : ""} ${srcBtn(s.source_id)}`).join("<br>") : unk("none")}<br><span class="muted">Данные о складском остатке не опубликованы.</span></dd>
        <dt>Сертификаты</dt><dd>${c.certificates.length ? c.certificates.map((x) => `${esc(x.name)} ${srcBtn(x.source_id)}`).join("<br>") : unk("none")}</dd>
        <dt>Полнота профиля</dt><dd>${cmp.n} из ${cmp.of} полей подтверждены источниками <span class="muted">(это не рейтинг)</span></dd>
      </dl></section>
  </div>
  <section class="sec"><div class="sec-h"><h2 class="h2">Что предприятие продаёт и может производить</h2><span class="muted">${sells.length} ${plural(sells.length, "позиция", "позиции", "позиций")} продукции · ${services.length} ${plural(services.length, "услуга", "услуги", "услуг")}</span></div>
    ${c.products.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Позиция</th><th>Тип</th><th>ОКПД2</th><th>Параметры</th><th>Цена</th><th>Источник</th><th></th></tr></thead><tbody>
    ${c.products.map((p) => `<tr><td><a href="#p.${p.id}">${esc(p.name)}</a></td><td>${p.kind === "service" ? "Услуга" : "Продукция"}</td><td>${okpdTag(p.okpd2)}</td><td>${p.params.map((x) => `${esc(x.name)}: ${x.value ? esc(x.value) : '<span class="unk">не указано</span>'}`).join("<br>") || unk("na")}</td><td>${unk("price")}</td><td>${srcBtn(p.source_id, domain(App.S[p.source_id]?.source_url || ""))}</td><td><button class="btn sm" data-act="rfq" data-product="${p.id}">Запросить</button></td></tr>`).join("")}
    </tbody></table></div>` : `<div class="note">Продукция в открытых источниках не найдена.</div>`}
  </section>
  <section class="sec grid2">
    <div><h2 class="h2" style="margin-bottom:12px">Что предприятие закупает</h2>
      ${reqs.length ? reqs.map(requestRow).join("") : `<div class="note">Предприятие не публиковало заявок на платформе. Данные о закупках в открытых источниках не собраны.</div>`}</div>
    <div><h2 class="h2" style="margin-bottom:12px">Предложения на платформе</h2>
      ${offers.length ? offers.map(offerRow).join("") : `<div class="note">Предложений, привязанных к предприятию, нет. Предложения размещают сами предприятия после подтверждения прав.</div>`}</div>
  </section>
  <section class="sec"><h2 class="h2" style="margin-bottom:12px">Возможные производственные связи</h2>
    ${rel.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Поставщик</th><th></th><th>Потребитель</th><th>Тип связи</th><th>Основание</th></tr></thead><tbody>
      ${rel.map((r) => `<tr><td><a href="#c.${r.from}">${esc(App.C[r.from].short)}</a><div class="muted">${esc(App.P[r.from_product]?.name)}</div></td><td>→</td><td><a href="#c.${r.to}">${esc(App.C[r.to].short)}</a><div class="muted">${esc(App.P[r.to_product]?.name)}</div></td><td>${relBadge(r.type)}</td><td>${esc(r.basis)}</td></tr>`).join("")}
    </tbody></table></div><p class="muted">Ни одна связь не подтверждена сторонами. POTENTIAL — совпадение продукции по источникам, INFERRED — вывод системы.</p>` : `<div class="note">Связи не определены.</div>`}
  </section>
  <section class="sec grid2">
    <div><h2 class="h2" style="margin-bottom:12px">Источники</h2><ul class="list">${c.sources.map((s) => `<li><span>${esc(s.source_title)}<br><span class="muted">${esc(s.source_type)} · приоритет ${s.priority} · ${s.fetch_status === "OK" ? "прочитан" : esc(s.fetch_status)}</span></span>${srcBtn(s.id, "Подробнее")}</li>`).join("")}</ul></div>
    <div><h2 class="h2" style="margin-bottom:12px">История изменений и отзывы</h2>
      <ul class="list"><li><span>${fmtDate(TODAY)} — первичный сбор данных из ${c.sources.length} ${plural(c.sources.length, "источника", "источников", "источников")}</span><span class="muted">crawler</span></li></ul>
      <p class="muted">Отзывов нет. Отзывы появляются только после подтверждённых взаимодействий на платформе.</p></div>
  </section></div>`;
};
const REL_TXT = { CONFIRMED_RELATION: "CONFIRMED · подтверждена", POTENTIAL_RELATION: "POTENTIAL · возможна", INFERRED_RELATION: "INFERRED · вывод системы" };
const relBadge = (t) => `<span class="st ${t === "CONFIRMED_RELATION" ? "VERIFIED" : t === "POTENTIAL_RELATION" ? "USER" : "UNVERIFIED"}">${REL_TXT[t]}</span>`;
const notFound = () => `<div class="wrap page"><h1 class="h1">Страница не найдена</h1><p><a href="#home">На главную</a></p></div>`;

/* ---------- Каталог продукции ---------- */
function allProducts() {
  return App.data.companies.flatMap((c) => c.products.map((p) => ({ ...p, company_id: c.id, c })))
    .filter((p) => App.showUnverified || ["VERIFIED", "PARTIALLY_VERIFIED"].includes(p.c.verification_status));
}
ROUTES.products = () => {
  const { f, q, sort } = UI.products;
  let list = allProducts().filter((p) => {
    if (f.kind && p.kind !== f.kind) return false;
    if (f.category && p.category !== f.category) return false;
    if (f.okpd2 && !(p.okpd2 && p.okpd2.code === f.okpd2)) return false;
    if (f.region && p.c.region !== f.region) return false;
    if (f.city && p.c.city !== f.city) return false;
    if (f.params && !p.params.some((x) => x.value)) return false;
    if (q) { const s = q.toLowerCase(); if (![p.name, p.category, p.c.name, p.okpd2?.code, p.description].join(" ").toLowerCase().includes(s)) return false; }
    return true;
  });
  const sorters = {
    name: (a, b) => a.name.localeCompare(b.name, "ru"),
    company: (a, b) => a.c.short.localeCompare(b.c.short, "ru"),
    distance: (a, b) => (distanceKm(App.profile.city, a.c.city) ?? 1e9) - (distanceKm(App.profile.city, b.c.city) ?? 1e9),
    data: (a, b) => (b.params.filter((x) => x.value).length + (b.okpd2 ? 1 : 0)) - (a.params.filter((x) => x.value).length + (a.okpd2 ? 1 : 0)),
    price: (a, b) => 0, volume: (a, b) => 0,
  };
  list.sort(sorters[sort] || sorters.name);
  const pg = list.slice((UI.products.page - 1) * PAGE_SIZE, UI.products.page * PAGE_SIZE);
  const cats = [...new Set(allProducts().map((p) => p.category))].sort();
  const codes = [...new Set(allProducts().filter((p) => p.okpd2).map((p) => p.okpd2.code))].sort();
  return `<div class="wrap page">${crumbs(["#products", "Каталог продукции"])}
  <div class="sec-h"><h1 class="h1">Каталог продукции и услуг</h1><a class="btn" href="#compare">Сравнение (${App.profile.compare.length})</a></div>
  <div class="cat"><aside class="filters" id="filters" aria-label="Фильтры">
    <div class="row" style="justify-content:space-between;margin-bottom:12px"><span class="label">Фильтры</span><button class="btn sm filters-toggle" data-act="filters-close">Показать ${list.length}</button></div>
    <fieldset><legend class="label">Тип</legend><select class="sel" data-f="products:kind"><option value="">Продукция и услуги</option><option value="product" ${f.kind === "product" ? "selected" : ""}>Продукция</option><option value="service" ${f.kind === "service" ? "selected" : ""}>Производственные услуги</option></select></fieldset>
    <fieldset><legend class="label">Категория</legend><select class="sel" data-f="products:category"><option value="">Любая</option>${cats.map((x) => `<option ${f.category === x ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></fieldset>
    <fieldset><legend class="label">ОКПД2</legend><select class="sel" data-f="products:okpd2"><option value="">Любой</option>${codes.map((x) => `<option value="${x}" ${f.okpd2 === x ? "selected" : ""}>${x} — ${esc(App.data.okpd2[x].slice(0, 44))}</option>`).join("")}</select></fieldset>
    <fieldset><legend class="label">Регион</legend><select class="sel" data-f="products:region"><option value="">Все</option>${Object.values(App.data.regions).map((r) => `<option value="${r.code}" ${f.region === r.code ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select></fieldset>
    <fieldset><legend class="label">Цена, объём, сроки, наличие</legend>
      <p class="muted" style="margin:0 0 8px">Ни одно предприятие не публикует цены, объёмы, сроки и наличие. Фильтры станут доступны, когда предприятия подтвердят данные.</p>
      <label class="chk"><input type="checkbox" data-fb2="params" ${f.params ? "checked" : ""}> Только с опубликованными характеристиками</label>
      <label class="chk"><input type="checkbox" id="show-unv" ${App.showUnverified ? "checked" : ""}> Показывать неподтверждённые данные</label>
    </fieldset>
    <button class="btn sm" data-act="reset-products">Сбросить фильтры</button>
  </aside>
  <div>
    <div class="toolbar">
      <div class="search" style="flex:1;min-width:240px"><label class="sr" for="pq">Поиск продукции</label><input id="pq" data-q="products" value="${esc(q)}" placeholder="Название, код ОКПД2, производитель"></div>
      <button class="btn filters-toggle" data-act="filters-open">Фильтры</button>
      <label class="sr" for="psort">Сортировка</label>
      <select class="sel" id="psort" data-sort="products">${[["name", "По названию"], ["company", "По производителю"], ["distance", "По расстоянию"], ["data", "По количеству подтверждённых данных"], ["price", "По цене (нет опубликованных цен)"], ["volume", "По объёму (нет опубликованных объёмов)"]].map(([v, t]) => `<option value="${v}" ${sort === v ? "selected" : ""}>${t}</option>`).join("")}</select>
    </div>
    <p class="muted" style="margin:0 0 12px">Найдено: ${list.length}</p>
    <div class="stack">${pg.map(productRow).join("") || '<div class="note">Нет позиций по выбранным фильтрам.</div>'}</div>
    ${pager("products", list.length)}
  </div></div></div>`;
};
function productRow(p) {
  const c = App.C[p.company_id];
  return `<article class="card" style="display:grid;grid-template-columns:88px minmax(0,1fr);gap:16px">
    <div class="photo">Фото не опубликовано</div>
    <div><div class="card-head"><div style="min-width:0"><span class="label">${p.kind === "service" ? "Услуга" : "Продукция"} · ${esc(p.category)}</span><h3 class="h3"><a href="#p.${p.id}">${esc(p.name)}</a></h3>
      <div class="muted"><a href="#c.${c.id}">${esc(c.name)}</a> · ${esc(c.city)}</div></div>${statusBadge(c.verification_status)}</div>
      <div class="row" style="margin-top:8px">${okpdTag(p.okpd2)} ${p.params.filter((x) => x.value).map((x) => `<span class="chip"><b>${esc(x.name)}</b>${esc(x.value)}</span>`).join("")}</div>
      <div class="row" style="margin-top:12px;justify-content:space-between"><span>${unk("price")}</span>
        <div class="row"><button class="btn sm pri" data-act="rfq" data-product="${p.id}">Запросить предложение</button><button class="btn sm" data-cmp="p:${p.id}">Сравнить</button>${srcBtn(p.source_id)}</div></div>
    </div></article>`;
}

/* ---------- Карточка продукции ---------- */
ROUTES.p = (id) => {
  const p = App.P[id]; if (!p) return notFound();
  const c = App.C[p.company_id];
  const q = { products: [], technologies: [], grades: [], missing: [] };
  const alts = App.data.companies.filter((x) => x.id !== c.id && x.products.some((pp) => pp.okpd2 && p.okpd2 && pp.okpd2.code === p.okpd2.code));
  return `<div class="wrap page">${crumbs(["#products", "Каталог продукции"], ["#c." + c.id, c.short], ["", p.name])}
  <div class="grid2" style="grid-template-columns:minmax(0,280px) minmax(0,1fr)">
    <div class="photo" style="max-width:280px">Фото не опубликовано в официальном каталоге</div>
    <div>
      <span class="label">${p.kind === "service" ? "Производственная услуга" : "Продукция"} · ${esc(p.category)}</span>
      <h1 class="h1">${esc(p.name)}</h1>
      <div class="muted" style="margin:4px 0 12px">Производитель: <a href="#c.${c.id}">${esc(c.name)}</a> ${statusBadge(c.verification_status)}</div>
      <div class="row">
        <button class="btn pri" data-act="rfq" data-product="${p.id}">Запросить предложение</button>
        <button class="btn" data-act="to-request" data-product="${p.id}">Добавить в заявку</button>
        <button class="btn" data-cmp="p:${p.id}">Сравнить</button>
        <button class="btn" data-act="to-chain" data-product="${p.id}">Добавить в производственную цепочку</button>
      </div>
    </div>
  </div>
  <div class="grid2 sec">
    <section><h2 class="h2" style="margin-bottom:12px">Характеристики</h2><dl class="kv">
      <dt>Описание</dt><dd>${p.description ? esc(p.description) : unk("na")}</dd>
      <dt>ОКПД2</dt><dd>${okpdTag(p.okpd2, true)}</dd>
      <dt>ОКВЭД производителя</dt><dd>${okvedTag(c.okved_main, true)}</dd>
      <dt>Материал</dt><dd>${p.materials?.length ? p.materials.map((m) => esc(m.name)).join(", ") + " " + srcBtn(p.materials[0].source_id) : unk("na")}</dd>
      ${p.params.map((x) => `<dt>${esc(x.name)}</dt><dd>${x.value ? esc(x.value) + " " + srcBtn(p.source_id) : unk("na")}</dd>`).join("")}
      <dt>Сертификаты, документы</dt><dd>${c.certificates.length ? c.certificates.map((x) => esc(x.name)).join("<br>") + ' <span class="muted">(сертификаты предприятия)</span>' : unk("none")}</dd>
    </dl></section>
    <section><h2 class="h2" style="margin-bottom:12px">Коммерческие условия</h2><dl class="kv">
      <dt>Цена</dt><dd>${unk("price")}</dd>
      <dt>Минимальная партия</dt><dd>${unk("na")}</dd>
      <dt>Доступный объём</dt><dd>${unk("none")}</dd>
      <dt>Производственная мощность</dt><dd>${c.capacities.filter((x) => !x.historical).map((x) => esc(x.text) + " " + srcBtn(x.source_id) + ' <span class="muted">(по предприятию в целом)</span>').join("<br>") || unk("none")}</dd>
      <dt>Срок производства</dt><dd>${unk("na")}</dd>
      <dt>Срок поставки</dt><dd>${unk("na")}</dd>
      <dt>Условия поставки</dt><dd>${unk("na")}</dd>
      <dt>Регион, склад</dt><dd>${esc(regionName(c.region))}, ${esc(c.city)} · <span class="muted">данные о складском остатке не опубликованы</span></dd>
      <dt>Источник</dt><dd>${srcBtn(p.source_id, App.S[p.source_id]?.source_title || "Источник")}</dd>
      <dt>Дата проверки</dt><dd>${fmtDate(p.last_verified_at)}</dd>
    </dl></section>
  </div>
  <section class="sec"><h2 class="h2" style="margin-bottom:12px">Другие производители с тем же классом ОКПД2</h2>
    ${alts.length ? `<div class="grid3">${alts.map(companyMini).join("")}</div>` : `<div class="note">В базе нет других предприятий с продукцией класса ${p.okpd2 ? esc(p.okpd2.code) : "—"}.</div>`}
  </section></div>`;
};
