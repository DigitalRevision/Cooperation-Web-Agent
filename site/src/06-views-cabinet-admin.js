/* ===== Личный кабинет и административная панель ===== */

ROUTES.cabinet = (arg) => {
  if (arg) UI.cabinetTab = arg;
  const t = UI.cabinetTab;
  const tabs = [["offers", "Мои предложения"], ["requests", "Мои заявки"], ["companies", "Мои предприятия"], ["warehouses", "Мои склады"], ["favorites", "Избранное"], ["saved", "Сохранённые поиски"], ["messages", "Сообщения"], ["settings", "Настройки"]];
  const myOffers = App.offers.filter((o) => o.author === App.uid), myReq = App.requests.filter((r) => r.author === App.uid);
  let body = "";
  if (t === "offers") body = `<div class="sec-h"><h2 class="h2">Мои предложения (${myOffers.length})</h2><button class="btn pri" data-act="offer-new">Разместить предложение</button></div>${myOffers.map(offerRow).join("") || '<div class="note">Вы ещё не размещали предложений.</div>'}`;
  if (t === "requests") body = `<div class="sec-h"><h2 class="h2">Мои заявки (${myReq.length})</h2><button class="btn pri" data-act="request-new">Создать заявку</button></div>${myReq.map(requestRow).join("") || '<div class="note">Вы ещё не создавали заявок.</div>'}`;
  if (t === "companies") body = `<div class="sec-h"><h2 class="h2">Мои предприятия</h2></div>
    <p class="muted">Привяжите предприятие к аккаунту, чтобы размещать предложения от его имени и подтверждать данные. Права подтверждаются модератором по документам.</p>
    ${App.profile.companies.length ? `<ul class="list">${App.profile.companies.map((x) => `<li><span><a href="#c.${x.company_id}">${esc(App.C[x.company_id]?.name)}</a><br><span class="muted">${esc(x.role)} · ${esc(x.status)}</span></span><button class="btn sm txt" data-act="unclaim" data-id="${x.company_id}">Отвязать</button></li>`).join("")}</ul>` : '<div class="note">Предприятий нет.</div>'}
    <form id="claim-form" class="form" style="margin-top:16px"><div class="field"><label for="cl-co">Предприятие</label><select class="sel" id="cl-co" name="company_id">${App.data.companies.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("")}</select></div>
    <div class="field"><label for="cl-role">Ваша роль</label><input class="inp" id="cl-role" name="role" required placeholder="например: отдел снабжения"></div>
    <div class="field" style="justify-content:flex-end"><button class="btn pri" type="submit">Отправить запрос на привязку</button></div></form>`;
  if (t === "warehouses") body = `<div class="sec-h"><h2 class="h2">Мои склады и площадки</h2></div>
    <p class="muted">Площадки и склады — отдельные сущности. Остатки указываются только вами и помечаются как «указано пользователем».</p>
    ${App.profile.warehouses.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Название</th><th>Тип</th><th>Адрес</th><th>Город</th><th>Складской объём</th><th>Доступный объём</th><th></th></tr></thead><tbody>${App.profile.warehouses.map((w) => `<tr><td>${esc(w.name)}</td><td>${esc(w.type)}</td><td>${esc(w.address)}</td><td>${esc(w.city)}</td><td>${w.capacity ? esc(w.capacity) : unk("na")}</td><td>${w.available ? esc(w.available) : unk("na")}</td><td><button class="btn sm txt" data-act="wh-del" data-id="${w.id}">Удалить</button></td></tr>`).join("")}</tbody></table></div>` : '<div class="note">Складов нет.</div>'}
    <form id="wh-form" class="form" style="margin-top:16px">
      <div class="field"><label for="wh-name">Название *</label><input class="inp" id="wh-name" name="name" required></div>
      <div class="field"><label for="wh-type">Тип</label><select class="sel" id="wh-type" name="type"><option>Склад</option><option>Завод</option><option>Цех</option><option>Производственная площадка</option><option>Филиал</option></select></div>
      <div class="field"><label for="wh-addr">Адрес</label><input class="inp" id="wh-addr" name="address"></div>
      <div class="field"><label for="wh-city">Город</label><select class="sel" id="wh-city" name="city">${Object.keys(App.data.cities).map((c) => `<option>${c}</option>`).join("")}</select></div>
      <div class="field"><label for="wh-cap">Складской объём</label><input class="inp" id="wh-cap" name="capacity" placeholder="например 2000 м²"></div>
      <div class="field"><label for="wh-av">Доступный объём</label><input class="inp" id="wh-av" name="available"></div>
      <div class="field full"><button class="btn pri" type="submit">Добавить</button></div></form>`;
  if (t === "favorites") {
    const fav = App.profile.favorites.map((k) => { const [tp, id] = k.split(":"); return tp === "c" ? App.C[id] && `<li><span><a href="#c.${id}">${esc(App.C[id].name)}</a></span><button class="btn sm txt" data-fav="${k}">Убрать</button></li>` : App.P[id] && `<li><span><a href="#p.${id}">${esc(App.P[id].name)}</a></span><button class="btn sm txt" data-fav="${k}">Убрать</button></li>`; }).filter(Boolean);
    body = `<h2 class="h2" style="margin-bottom:12px">Избранное</h2>${fav.length ? `<ul class="list">${fav.join("")}</ul>` : '<div class="note">Сохраняйте предприятия кнопкой «В избранное».</div>'}`;
  }
  if (t === "saved") body = `<h2 class="h2" style="margin-bottom:12px">Сохранённые поиски</h2>${App.profile.saved.length ? `<ul class="list">${App.profile.saved.map((s, i) => `<li><span>${esc(s.text)}<br><span class="muted">${fmtDate(s.at)}</span></span><span class="row"><button class="btn sm" data-act="saved-run" data-i="${i}">Повторить</button><button class="btn sm txt" data-act="saved-del" data-i="${i}">Удалить</button></span></li>`).join("")}</ul>` : '<div class="note">Сохраните поиск на странице «Поиск поставщика».</div>'}`;
  if (t === "messages") {
    const inbox = myReq.flatMap((r) => (r.responses || []).map((x) => ({ ...x, r })));
    const sent = App.requests.flatMap((r) => (r.responses || []).filter((x) => x.author === App.uid).map((x) => ({ ...x, r })));
    body = `<h2 class="h2" style="margin-bottom:12px">Сообщения</h2>
      <div class="grid2"><div><div class="label" style="margin-bottom:8px">Отклики на мои заявки (${inbox.length})</div>${inbox.map((m) => `<div class="card flat" style="margin-bottom:8px"><b>${esc(m.company)}</b> → <a href="#r.${m.r.id}">${esc(m.r.what)}</a><div class="muted">${fmtDate(m.at)}</div><div>${esc(m.text)}</div></div>`).join("") || '<div class="note">Откликов нет.</div>'}</div>
      <div><div class="label" style="margin-bottom:8px">Мои отклики (${sent.length})</div>${sent.map((m) => `<div class="card flat" style="margin-bottom:8px"><a href="#r.${m.r.id}">${esc(m.r.what)}</a><div class="muted">${fmtDate(m.at)}</div><div>${esc(m.text)}</div></div>`).join("") || '<div class="note">Вы не откликались на заявки.</div>'}</div></div>`;
  }
  if (t === "settings") body = `<h2 class="h2" style="margin-bottom:12px">Настройки</h2>
    <form id="settings-form" class="form"><div class="field"><label for="st-city">Город вашего предприятия (для расчёта расстояний)</label><select class="sel" id="st-city" name="city">${Object.keys(App.data.cities).map((c) => `<option ${App.profile.city === c ? "selected" : ""}>${c}</option>`).join("")}</select></div>
    <div class="field" style="justify-content:flex-end"><button class="btn pri" type="submit">Сохранить</button></div></form>
    <dl class="kv" style="margin-top:24px"><dt>Хранение данных</dt><dd>${App.mode === "db" ? "Общая база платформы: заявки и предложения видят все участники; цепочки, избранное и склады — только вы." : "Локально в этом браузере (общая база недоступна в этом просмотре)."}</dd>
    <dt>Роли</dt><dd>Один аккаунт — покупатель и продавец одновременно.</dd></dl>`;
  return `<div class="wrap page">${crumbs(["#cabinet", "Личный кабинет"])}
  <div class="sec-h"><h1 class="h1">Личный кабинет</h1><div class="row"><a class="btn" href="#chains">Мои цепочки (${App.chains.length})</a><a class="btn" href="#compare">Сравнение (${App.profile.compare.length})</a></div></div>
  <div class="tabs" role="tablist">${tabs.map(([k, n]) => `<button role="tab" aria-selected="${t === k}" data-ctab="${k}">${n}</button>`).join("")}</div>${body}</div>`;
};

/* ---------- Админ-панель ---------- */
ROUTES.admin = (arg) => {
  if (arg) UI.adminTab = arg;
  if (!App.canEdit) return `<div class="wrap page">${crumbs(["#admin", "Администрирование"])}<h1 class="h1">Административная панель</h1><div class="note" style="margin-top:16px">Раздел доступен пользователям с правом редактирования платформы.</div></div>`;
  const t = UI.adminTab;
  const tabs = [["companies", "Предприятия"], ["sources", "Источники"], ["crawler", "Crawler jobs"], ["errors", "Ошибки краулера"], ["moderation", "Модерация"], ["reports", "Жалобы"], ["dict", "ОКВЭД / ОКПД2"], ["ai", "AI-индексация"], ["history", "История изменений"], ["arch", "Архитектура"]];
  let body = "";
  if (t === "companies") body = `<div class="tbl-wrap"><table class="tbl sticky"><thead><tr><th>Предприятие</th><th>ИНН</th><th>Регион</th><th>Статус</th><th>Полнота</th><th>Расхождения</th><th>Источники</th><th>Действие</th></tr></thead><tbody>
    ${App.data.companies.map((c) => `<tr><td><a href="#c.${c.id}">${esc(c.short)}</a></td><td class="num">${c.inn ? esc(c.inn) : unk("conf")}</td><td>${esc(c.city)}</td><td>${statusBadge(c.verification_status)}</td><td class="num">${completeness(c).n}/${completeness(c).of}</td><td>${(c.discrepancies || []).length}</td><td>${c.sources.length}</td>
    <td><select class="sel" aria-label="Статус" data-setstatus="${c.id}">${["VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED", "OUTDATED"].map((s) => `<option ${c.verification_status === s ? "selected" : ""}>${s}</option>`).join("")}</select></td></tr>`).join("")}
    </tbody></table></div><p class="muted">Смена статуса записывается в журнал аудита. Правка значений предприятия выполняется через Git-репозиторий данных (pull request с источником).</p>`;
  if (t === "sources") body = `<div class="tbl-wrap"><table class="tbl sticky"><thead><tr><th>Источник</th><th>Предприятие</th><th>Тип</th><th>Приоритет</th><th>Обход</th><th>Проверено</th><th>Статус</th></tr></thead><tbody>
    ${Object.values(App.S).map((s) => `<tr><td><button class="srcbtn" data-src="${s.id}">${esc(s.source_title)}</button><div class="muted">${esc(domain(s.source_url))}</div></td><td>${esc(App.C[s.company_id].short)}</td><td>${esc(s.source_type)}</td><td>${s.priority}</td><td>${s.fetch_status === "OK" ? '<span class="v yes">OK</span>' : `<span class="v no">${esc(s.fetch_status)}</span>`}</td><td>${fmtDate(s.last_verified_at)}</td>
    <td><label class="chk"><input type="checkbox" data-srcflag="${s.id}" ${srcActive(s.id) ? "checked" : ""}> Используется</label></td></tr>`).join("")}
    </tbody></table></div><p class="muted">Отключённый источник исключается из сопоставления: позиции продукции, подтверждённые только им, не попадают в результаты поиска.</p>`;
  if (t === "crawler" || t === "errors") {
    const log = App.data.crawl_log.filter((x) => t === "crawler" || x.status !== "OK");
    const queued = (App.reports || []).filter((r) => r.kind === "recrawl");
    body = `${t === "crawler" ? `<div class="grid3" style="margin-bottom:16px"><div class="stat"><b class="num">${App.data.crawl_log.length}</b><span class="muted">запросов в задании 24.09.2026</span></div><div class="stat"><b class="num">${App.data.crawl_log.filter((x) => x.status === "OK").length}</b><span class="muted">успешно прочитано</span></div><div class="stat"><b class="num">${App.data.crawl_log.filter((x) => x.status !== "OK").length}</b><span class="muted">ошибок (403, robots.txt, редиректы)</span></div></div>` : ""}
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>URL</th><th>Статус</th><th>Комментарий</th><th>Дата</th><th></th></tr></thead><tbody>
    ${log.map((x) => `<tr><td style="overflow-wrap:anywhere"><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.url)}</a></td><td>${x.status === "OK" ? '<span class="v yes">OK</span>' : `<span class="v no">${esc(x.status)}</span>`}</td><td>${esc(x.note)}</td><td>${fmtDate(x.fetched_at)}</td><td><button class="btn sm" data-act="recrawl" data-url="${esc(x.url)}">Повторить обход</button></td></tr>`).join("")}
    </tbody></table></div>
    ${queued.length ? `<h3 class="h3" style="margin:24px 0 8px">Очередь повторного обхода (${queued.length})</h3><ul class="list">${queued.map((q) => `<li><span style="overflow-wrap:anywhere">${esc(q.url)}</span><span class="muted">поставлено ${fmtDate(q.created_at)} · ожидает воркер crawler</span></li>`).join("")}</ul>` : ""}
    <p class="muted">Воркер обхода (Scrapy + очередь Redis) соблюдает robots.txt, ограничивает частоту запросов и повторяет только временные ошибки. В этом прототипе очередь хранится на платформе, а воркер запускается из репозитория <code>crawler/</code>.</p>`;
  }
  if (t === "moderation") body = `<h3 class="h3" style="margin-bottom:8px">Предложения (${App.offers.length})</h3>${modTable(App.offers, "offers", (o) => o.title)}
    <h3 class="h3" style="margin:24px 0 8px">Заявки (${App.requests.length})</h3>${modTable(App.requests, "requests", (r) => r.what)}`;
  if (t === "reports") { const reps = (App.reports || []).filter((r) => r.kind === "data_error"); body = reps.length ? `<ul class="list">${reps.map((r) => `<li><span><a href="#c.${r.company_id}">${esc(App.C[r.company_id]?.short)}</a> · ${esc(r.field || "")}<br>${esc(r.text)}<br><span class="muted">${fmtDate(r.created_at)}</span></span><button class="btn sm" data-act="report-close" data-id="${r.id}">Закрыть</button></li>`).join("")}</ul>` : '<div class="note">Жалоб нет.</div>'; }
  if (t === "dict") body = `<div class="grid2"><div><h3 class="h3" style="margin-bottom:8px">ОКВЭД (${Object.keys(App.data.okved).length})</h3><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Код</th><th>Наименование</th><th>Предприятий</th></tr></thead><tbody>${Object.entries(App.data.okved).map(([k, v]) => `<tr><td>${okvedTag(k)}</td><td>${esc(v)}</td><td class="num">${App.data.companies.filter((c) => c.okved_main === k).length}</td></tr>`).join("")}</tbody></table></div></div>
    <div><h3 class="h3" style="margin-bottom:8px">ОКПД2 (${Object.keys(App.data.okpd2).length})</h3><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Класс</th><th>Наименование</th><th>Позиций</th></tr></thead><tbody>${Object.entries(App.data.okpd2).map(([k, v]) => `<tr><td><span class="code okpd2"><span>${k}</span></span></td><td>${esc(v)}</td><td class="num">${Object.values(App.P).filter((p) => p.okpd2?.code === k).length}</td></tr>`).join("")}</tbody></table></div>
    <p class="muted">Все коды ОКПД2 в базе имеют статус INFERRED: присвоены по классификатору и ждут подтверждения предприятием или по ГИСП.</p></div></div>`;
  if (t === "ai") { const docs = App.data.companies.length + Object.keys(App.P).length + Object.keys(App.S).length; body = `<dl class="kv"><dt>Документов для индексации</dt><dd class="num">${docs} (предприятия, позиции продукции, источники)</dd><dt>Режим AI-поиска</dt><dd>${App.sample ? "Разбор запроса через Claude доступен; поиск — только по базе." : "Разбор по правилам; AI-разбор недоступен в этом просмотре."}</dd>
    <dt>Полнотекстовый индекс</dt><dd>PostgreSQL FTS (russian) — в <code>backend/</code></dd><dt>Эмбеддинги</dt><dd>pgvector, пересчёт после каждого коммита в Git-репозиторий данных</dd>
    <dt>Правило</dt><dd>AI получает только найденные записи с их источниками и не отвечает фактами вне базы. Если данных нет — «Информация не найдена в открытых источниках».</dd></dl>`; }
  if (t === "history") { const aud = (App.reports || []).filter((r) => r.kind === "audit"); body = `<ul class="list"><li><span>Первичный сбор: ${App.data.companies.length} предприятий, ${Object.keys(App.P).length} позиций, ${Object.keys(App.S).length} источников</span><span class="muted">${fmtDate(App.data.generated_at)} · crawler</span></li>${aud.map((a) => `<li><span>${esc(a.text)}</span><span class="muted">${fmtDate(a.created_at)}</span></li>`).join("")}</ul>`; }
  if (t === "arch") body = archHtml();
  return `<div class="wrap page">${crumbs(["#admin", "Администрирование"])}
  <h1 class="h1">Административная панель</h1>
  <div class="tabs" role="tablist" style="margin-top:16px">${tabs.map(([k, n]) => `<button role="tab" aria-selected="${t === k}" data-atab="${k}">${n}</button>`).join("")}</div>${body}</div>`;
};
function modTable(rows, coll, title) {
  if (!rows.length) return '<div class="note">Записей нет.</div>';
  return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Название</th><th>Дата</th><th>Статус</th><th>Действия</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${esc(title(r))}</td><td>${fmtDate(r.created_at)}</td><td>${esc(r.status || "NEW")}</td><td class="row"><button class="btn sm" data-mod="${coll}:${r.id}:APPROVED">Одобрить</button><button class="btn sm danger" data-mod="${coll}:${r.id}:REJECTED">Отклонить</button></td></tr>`).join("")}</tbody></table></div>`;
}
function archHtml() {
  return `<section><h3 class="h3">Главный принцип</h3><div class="pipe" style="margin:8px 0 24px"><span class="k">Реальные данные</span><i>→</i><span>Проверенные источники</span><i>→</i><span>Поиск</span><i>→</i><span>Сопоставление</span><i>→</i><span>Производственная цепочка</span><i>→</i><span>Поставщик</span><i>→</i><span>Заявка</span><i>→</i><span class="k">Кооперация</span></div>
  <h3 class="h3">Сбор данных</h3><div class="pipe" style="margin:8px 0 24px"><span>Сайты предприятий, ЕГРЮЛ, ГИСП, каталоги</span><i>→</i><span class="k">Crawler (Scrapy, robots.txt, rate limit)</span><i>→</i><span>Извлечение и нормализация</span><i>→</i><span>Дедупликация, валидация</span><i>→</i><span class="k">Git: data/companies/…</span><i>→</i><span>CI-проверка схемы</span><i>→</i><span>Загрузка в PostgreSQL</span><i>→</i><span>FTS + эмбеддинги</span></div>
  <h3 class="h3">AI-поиск</h3><div class="pipe" style="margin:8px 0 24px"><span class="k">Пользователь</span><i>→</i><span>AI Parser</span><i>→</i><span>Structured Query</span><i>→</i><span>Database Search</span><i>→</i><span>OKVED</span><i>→</i><span>OKPD2</span><i>→</i><span>Product</span><i>→</i><span>Material</span><i>→</i><span>Technology</span><i>→</i><span>Geography</span><i>→</i><span>Capacity</span><i>→</i><span>Ranking</span><i>→</i><span class="k">Explainable Result</span></div>
  <div class="grid2"><div><h3 class="h3" style="margin-bottom:8px">Git-репозиторий данных</h3><pre class="code-block">data/
  companies/&lt;id&gt;/company.json
  companies/&lt;id&gt;/products.json
  companies/&lt;id&gt;/sources.json
  products/&lt;product_id&gt;.json
  okved/okved.json
  okpd2/okpd2.json
  materials/materials.json
  technologies/technologies.json
  regions/regions.json, cities.json
  relations/relations.json
  warehouses/
  sources/sources.json
  sources/crawl_log_YYYY-MM-DD.json</pre></div>
  <div><h3 class="h3" style="margin-bottom:8px">API (FastAPI)</h3><pre class="code-block">GET  /api/v1/companies?region=&amp;okved=&amp;status=&amp;page=
GET  /api/v1/companies/{id}
GET  /api/v1/products?okpd2=&amp;q=&amp;page=
POST /api/v1/search/parse        (AI parser)
POST /api/v1/search              (structured query → explainable results)
GET  /api/v1/okved, /okpd2, /materials, /technologies
CRUD /api/v1/offers, /requests, /warehouses
CRUD /api/v1/chains, /chains/{id}/nodes
POST /api/v1/chains/{id}/nodes/{nid}/alternatives
GET  /api/v1/sources/{id}
POST /api/v1/admin/crawl-jobs     GET /admin/crawl-errors
PATCH /api/v1/admin/companies/{id}/status</pre></div></div>
  <h3 class="h3" style="margin:24px 0 8px">Сущности БД (PostgreSQL)</h3><p class="muted">User, Organization, OrganizationBranch, Warehouse, Product, ProductSpecification, Material, Technology, OKVED, OKPD2, OrganizationOKVED, ProductOKPD2, ProductMaterial, ProductTechnology, Offer, PurchaseRequest, Supplier, SupplierOffer, ProductionChain, ProductionChainNode, ProductionChainEdge, Certificate, Document, Source, FieldSource, CrawlJob, CrawlResult, Review, Message, Favorite, Comparison, AIQuery, AuditLog.</p>
  <h3 class="h3" style="margin:24px 0 8px">Безопасность</h3><p class="muted">RBAC (user, company_admin, moderator, admin), JWT с коротким сроком, rate limiting, Pydantic-валидация, ORM-параметризация против SQL-инъекций, экранирование вывода и CSP против XSS, CSRF-токены для cookie-сессий, аудит всех изменений, bcrypt/argon2 для паролей, изолированная сеть для crawler, админ-панель за SSO и IP-ограничением.</p></section>`;
}
