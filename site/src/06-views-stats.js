/* ===== Статистика: предприятия и продукция по регионам и отраслям, источники, ход сбора (GET /api/v1/overview) ===== */
const OV = { data: null, loading: false, error: null, at: 0 };
const nf = (n) => (n == null ? "—" : Math.round(n).toLocaleString("ru-RU"));
const bln = (k) => (k ? (k / 1e6).toLocaleString("ru-RU", { maximumFractionDigits: 1 }) : "—");   // тыс. ₽ → млрд ₽
const VERIF = { VERIFIED: "Подтверждены", PARTIALLY_VERIFIED: "Частично подтверждены", UNVERIFIED: "Не подтверждены", OUTDATED: "Закрыты или устарели" };

async function loadOverview() {
  if (OV.loading) return;
  OV.loading = true;
  try { OV.data = await API.call("GET", "/api/v1/overview"); OV.error = null; }
  catch (e) { OV.error = e.message || "Сервер платформы недоступен"; }
  OV.loading = false; OV.at = Date.now();
  if (route().name === "stats") rerender();
}
// Пока раздел открыт, данные обновляются раз в 30 секунд: сбор и обход сайтов идут в фоне
let _ovTimer = 0;
function watchOverview() {
  if (!OV.at || Date.now() - OV.at > 30000) loadOverview();
  if (_ovTimer) return;
  _ovTimer = setInterval(() => {
    if (route().name !== "stats") { clearInterval(_ovTimer); _ovTimer = 0; return; }
    loadOverview();
  }, 30000);
}

const ovBar = (n, max) => `<span class="ov-bar" aria-hidden="true"><i style="width:${max ? Math.max(1, Math.round(100 * n / max)) : 0}%"></i></span>`;
const ovKpi = (v, t) => `<div class="stat ov-t"><b class="num">${v}</b><span class="muted">${t}</span></div>`;

function ovCollection(col) {
  if (!col) return "";
  const s = col.sync || {}, last = s.last_run || {}, st = last.stats || {};
  const now = s.running || s.state === "running"
    ? `<p><b>Сбор идёт</b>${s.stage ? ` — ${esc(s.stage)}` : ""}${s.total ? `: ${nf(s.done)} из ${nf(s.total)}` : ""}${s.found ? `. Найдено в реестрах ФНС: ${nf(s.found)} организаций` : ""}${s.new ? `, новых в этом запуске: ${nf(s.new)}` : ""}.</p>`
    : `<p><b>Сбор сейчас не идёт.</b></p>`;
  const lastTxt = last.at ? `<p class="muted">Последний законченный сбор: ${dt(last.at)} — ${dt(last.finished)}. Найдено в реестрах: ${nf(last.found)} организаций,
    добавлено ${nf(st.added)}, проверено ${nf(st.checked)}${last.queued_new ? `, ещё ${nf(last.queued_new)} в очереди` : ""}; продукция обновлена у ${nf(st.products_updated)} предприятий.</p>` : "";
  const crawl = (col.crawl || []).map((r) => {
    const x = r.stats || {}, a = r.applied || {};
    return `<tr><td>${dt(r.started_at)}</td><td>${r.kind === "nightly" ? "поиск и обход сайтов" : "задания из админ-панели"}</td>
      <td>${r.finished_at ? (r.status === "OK" ? "закончен" : "прерван") + " " + dt(r.finished_at) : "идёт"}</td>
      <td class="num">${nf(x.pages)}</td><td class="num">${nf(x.searched)}</td><td class="num">${nf(x.sites_confirmed)}</td>
      <td class="num">${r.applied ? `${nf(a.sites)} / ${nf(a.products)}` : "—"}</td></tr>`;
  }).join("");
  return `<section class="sec card"><div class="label">Сбор данных</div>${now}${lastTxt}
    ${crawl ? `<h3 class="ov-h3">Краулер официальных сайтов</h3><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Начат</th><th>Запуск</th><th>Состояние</th>
      <th>Страниц</th><th>Сайт искали</th><th>Сайтов найдено</th><th>В карточки: сайты / позиции</th></tr></thead><tbody>${crawl}</tbody></table></div>` : ""}</section>`;
}

function ovTable(rows, first, key) {
  const max = Math.max(...rows.map((r) => r.companies), 0);
  return `<div class="tbl-wrap"><table class="tbl sticky"><thead><tr><th>${first}</th><th>Предприятий</th><th>Действующих</th><th>С продукцией</th>
    <th>Позиций продукции</th><th>С сайтом</th><th>Выручка, млрд ₽</th><th>Численность</th></tr></thead><tbody>
    ${rows.map((r) => `<tr><td>${esc(r[key])}</td><td class="num ov-cell"><span>${nf(r.companies)}</span>${ovBar(r.companies, max)}</td><td class="num">${nf(r.active)}</td>
      <td class="num">${nf(r.withProducts)}</td><td class="num">${nf(r.products)}</td><td class="num">${nf(r.withSite)}</td>
      <td class="num">${bln(r.revenueK)}</td><td class="num">${nf(r.headcount)}</td></tr>`).join("")}</tbody></table></div>`;
}

function ovTop(items, title, what) {
  if (!items.length) return "";
  return `<div><h3 class="ov-h3">${title}</h3><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Предприятие</th><th>Регион</th><th>${what === "rev" ? "Выручка, млрд ₽" : "Позиций"}</th></tr></thead><tbody>
    ${items.map((c) => `<tr><td><a href="#c.${esc(c.id)}">${esc(c.name)}</a><div class="muted">${esc(c.industry || "")}</div></td><td>${esc(c.region || "—")}</td>
      <td class="num">${what === "rev" ? bln(c.revenueK) : nf(c.products)}</td></tr>`).join("")}</tbody></table></div></div>`;
}

ROUTES.stats = () => {
  watchOverview();
  const d = OV.data;
  const head = `${crumbs(["#stats", "Статистика"])}<div class="sec-h"><div><h1 class="h1">Статистика</h1>
    <p class="muted" style="margin:4px 0 0">Предприятия обрабатывающей промышленности России в базе платформы и их продукция${d ? ` · ревизия каталога ${esc(d.revision)}` : ""}${OV.at ? ` · обновлено ${new Date(OV.at).toLocaleTimeString("ru-RU")}` : ""}</p></div>
    <button class="btn sm" data-ov-refresh>Обновить</button></div>`;
  if (!d) return `<div class="wrap page">${head}${OV.error ? `<div class="note warn">Статистика недоступна: ${esc(OV.error)}. Раздел работает, когда сайт открыт с сервера платформы.</div>` : `<p class="muted">Загрузка…</p>`}</div>`;
  const t = d.totals, maxDay = Math.max(...d.addedByDay.map(([, n]) => n), 0);
  const maxV = Math.max(...Object.values(d.verification), 0);
  const verif = Object.entries(d.verification).sort((a, b) => b[1] - a[1]).map(([k, n]) => `<li><span>${esc(VERIF[k] || k)}</span><b class="num">${nf(n)}</b>${ovBar(n, maxV)}</li>`).join("");
  return `<div class="wrap page">${head}
    <section><div class="ov-kpi">
      ${ovKpi(nf(t.companies), "предприятий в базе")}${ovKpi(nf(t.active), "действующих")}${ovKpi(nf(t.regions), "регионов")}
      ${ovKpi(nf(t.products), "позиций продукции")}${ovKpi(nf(t.withProducts), "предприятий с продукцией")}${ovKpi(nf(t.withSite), "с официальным сайтом")}
      ${ovKpi(bln(t.revenueK), "млрд ₽ выручки за последний год")}${ovKpi(nf(t.headcount), "сотрудников (по данным ФНС)")}
    </div></section>
    ${ovCollection(d.collection)}
    <section class="sec grid2">
      <div><h2 class="h2">Продукция по источникам</h2><div class="tbl-wrap" style="margin-top:12px"><table class="tbl"><thead><tr><th>Источник</th><th>Позиций</th><th>Предприятий</th></tr></thead><tbody>
        ${d.productSources.map((s) => `<tr><td>${esc(s.name)}</td><td class="num">${nf(s.products)}</td><td class="num">${nf(s.companies)}</td></tr>`).join("") || `<tr><td colspan="3">Продукции пока нет</td></tr>`}</tbody></table></div></div>
      <div><h2 class="h2">Добавлено в базу по дням</h2><div class="tbl-wrap" style="margin-top:12px"><table class="tbl"><tbody>
        ${d.addedByDay.slice().reverse().map(([day, n]) => `<tr><td>${fmtDate(day)}</td><td class="num ov-cell"><span>${nf(n)}</span>${ovBar(n, maxDay)}</td></tr>`).join("")}</tbody></table></div>
        <h3 class="ov-h3">Проверка реквизитов</h3><ul class="ov-list">${verif}</ul></div>
    </section>
    <section class="sec"><h2 class="h2">По регионам</h2><p class="muted">${nf(d.regions.length)} ${plural(d.regions.length, "регион", "региона", "регионов")}; выручка — за последний опубликованный год (ГИР БО ФНС)</p>${ovTable(d.regions, "Регион", "name")}</section>
    <section class="sec"><h2 class="h2">По отраслям</h2><p class="muted">Отрасль — по основному коду ОКВЭД</p>${ovTable(d.industries, "Отрасль", "name")}</section>
    <section class="sec grid2">${ovTop(d.topRevenue, "Крупнейшие по выручке", "rev")}${ovTop(d.topProducts, "Больше всего продукции", "prod")}</section>
  </div>`;
};
document.addEventListener("click", (e) => { if (e.target.closest("[data-ov-refresh]")) { OV.at = 0; loadOverview(); } });
