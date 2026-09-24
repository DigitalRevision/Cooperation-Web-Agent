/* ===== События и запуск ===== */

/* ---------- Ручные изменения статусов модератором поверх базы ---------- */
function applyOverrides() {
  for (const c of App.data.companies) { if (c._orig == null) c._orig = c.verification_status; c.verification_status = c._orig; }
  for (const r of (App.reports || []).filter((x) => x.kind === "override").sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""))) {
    if (App.C[r.company_id]) App.C[r.company_id].verification_status = r.status;
  }
}
const _render0 = render;
render = function () { if (App.data) applyOverrides(); _render0(); };

/* ---------- Вспомогательные функции форм и журнал действий ---------- */
const formData = (f) => Object.fromEntries(new FormData(f).entries());
const audit = (text) => Store.put("reports", "a-" + uidGen(), { kind: "audit", text, author: App.uid, created_at: nowIso() });

/* ---------- Отправка форм: поиск, заявки, предложения, цепочки, настройки ---------- */
document.addEventListener("submit", async (e) => {
  const f = e.target; e.preventDefault();
  if (f.id === "reg-form") { regNext(); return; }
  const d = formData(f);
  if (f.id === "home-search" || f.id === "main-search") { if (d.q.trim()) runSearch(d.q.trim(), false); return; }
  if (f.id === "offer-form") {
    const co = App.data.companies.find((c) => c.name === d.company_name);
    const id = "o-" + uidGen();
    const ok = await Store.put("offers", id, { title: d.title, kind_label: d.kind_label, company_name: d.company_name, company_id: co?.id || null, description: d.description, material: d.material, okpd2: d.okpd2, specs: d.specs, qty: d.qty, unit: d.unit,
      price: d.price ? { value: Number(String(d.price).replace(",", ".")), currency: "₽", unit: d.price_unit || d.unit, date: TODAY } : null,
      min_batch: d.min_batch, lead_prod: d.lead_prod, lead_deliv: d.lead_deliv, city: d.city, warehouse: d.warehouse, terms: d.terms, docs: d.docs, author: App.uid, status: "NEW", created_at: nowIso() });
    if (ok) { closePanel(); toast("Предложение опубликовано и ожидает модерации."); location.hash = "#sell"; }
    return;
  }
  if (f.id === "request-form") {
    const id = "r-" + uidGen();
    const ok = await Store.put("requests", id, { ...d, region_name: d.region ? regionName(d.region) : "Любой", author: App.uid, status: "NEW", responses: [], created_at: nowIso(), company_id: null });
    if (ok) { closePanel(); toast(d.target_company ? "Запрос отправлен." : "Заявка создана. Показаны потенциальные поставщики."); location.hash = "#r." + id; }
    return;
  }
  if (f.id === "respond-form") {
    const r = App.requests.find((x) => x.id === f.dataset.id); if (!r) return;
    const responses = [...(r.responses || []), { company: d.company, text: d.text, price: d.price || null, author: App.uid, at: nowIso() }];
    const { id, ...rest } = r;
    if (await Store.put("requests", r.id, { ...rest, responses })) toast("Отклик отправлен.");
    return;
  }
  if (f.id === "to-chain-form") {
    const pid = f.dataset.product || d.product;
    const node = { id: uidGen(), step: d.step, company_id: f.dataset.company, product_id: pid || null, status: "SELECTED", history: [] };
    let ch = d.chain === "__new" ? { id: "chain-" + uidGen(), title: "Новая цепочка", buyer_city: App.profile.city, nodes: [], edges: [], created_at: nowIso() } : JSON.parse(JSON.stringify(App.chains.find((c) => c.id === d.chain)));
    const prev = ch.nodes[ch.nodes.length - 1];
    ch.nodes.push(node);
    if (prev) ch.edges.push({ from: prev.id, to: node.id, type: relType(prev, node) });
    closePanel(); await Store.saveChain(ch); location.hash = "#ch." + ch.id; toast("Этап добавлен в цепочку.");
    return;
  }
  if (f.id === "node-form") {
    const ch = JSON.parse(JSON.stringify(App.chains.find((c) => c.id === f.dataset.chain)));
    if (f.dataset.node) { const nd = ch.nodes.find((n) => n.id === f.dataset.node); nd.step = d.step; nd.req_text = d.req_text; }
    else { const nd = { id: uidGen(), step: d.step, req_text: d.req_text, company_id: null, product_id: null, status: "EMPTY", history: [] }; const prev = ch.nodes[ch.nodes.length - 1]; ch.nodes.push(nd); if (prev) ch.edges.push({ from: prev.id, to: nd.id, type: "INFERRED_RELATION" }); }
    closePanel(); await Store.saveChain(ch); return;
  }
  if (f.id === "edge-form") {
    const ch = JSON.parse(JSON.stringify(App.chains.find((c) => c.id === f.dataset.chain)));
    let e = edgeFor(ch, f.dataset.from, f.dataset.to); if (!e) { e = { from: f.dataset.from, to: f.dataset.to }; ch.edges.push(e); }
    Object.assign(e, d); closePanel(); await Store.saveChain(ch); toast("Связь сохранена."); return;
  }
  if (f.id === "claim-form") { if (!App.profile.companies.some((x) => x.company_id === d.company_id)) App.profile.companies.push({ company_id: d.company_id, role: d.role, status: "Ожидает подтверждения модератором" }); await Store.saveProfile(); rerender(); toast("Запрос на привязку отправлен."); return; }
  if (f.id === "wh-form") { App.profile.warehouses.push({ id: uidGen(), ...d }); await Store.saveProfile(); rerender(); toast("Склад добавлен."); return; }
  if (f.id === "settings-form") { App.profile.city = d.city; await Store.saveProfile(); rerender(); toast("Настройки сохранены."); return; }
  if (f.id === "report-form") { await Store.put("reports", "d-" + uidGen(), { kind: "data_error", company_id: f.dataset.company, field: d.field, text: d.text, author: App.uid, created_at: nowIso() }); closePanel(); toast("Сообщение передано модератору."); return; }
  if (f.id === "rename-form") { const ch = JSON.parse(JSON.stringify(App.chains.find((c) => c.id === f.dataset.chain))); ch.title = d.title; closePanel(); await Store.saveChain(ch); return; }
});

/* ---------- Клики: кнопки действий, избранное, сравнение, вкладки ---------- */
document.addEventListener("click", async (e) => {
  const t = e.target.closest("button,[data-act]"); if (!t) return;
  if (t.dataset.regPick) { regPick(t.dataset.regPick); return; }
  if (t.dataset.regPickName) { regPick(null, t.dataset.regPickName); return; }
  if (t.dataset.example) { runSearch(t.dataset.example, false); return; }
  if (t.dataset.fav) { toggleList("favorites", t.dataset.fav); return; }
  if (t.dataset.cmp) { toggleList("compare", t.dataset.cmp); return; }
  if (t.dataset.page) { const [k, n] = t.dataset.page.split(":"); UI[k].page = Number(n); render(); window.scrollTo(0, 0); return; }
  if (t.dataset.ctab) { location.hash = "#cabinet." + t.dataset.ctab; return; }
  if (t.dataset.atab) { location.hash = "#admin." + t.dataset.atab; return; }
  if (t.dataset.sellf != null) { UI.sellFilter = t.dataset.sellf; render(); return; }
  if (t.dataset.mod) { const [coll, id, st] = t.dataset.mod.split(":"); const r = App[coll].find((x) => x.id === id); if (r) { const { id: _i, ...rest } = r; await Store.put(coll, id, { ...rest, status: st }); audit(`Модерация: ${coll === "offers" ? "предложение" : "заявка"} «${coll === "offers" ? r.title : r.what}» → ${st}`); } return; }
  const a = t.dataset.act; if (!a) return;
  // Регистрация: навигация по шагам
  if (a === "reg-back") { UI.reg.errors = {}; UI.reg.step--; render(); window.scrollTo(0, 0); return; }
  if (a === "reg-clear") { Object.assign(UI.reg, { co: {}, from: null, fromKeys: [], checked: false, errors: {} }); render(); return; }
  if (a === "reg-finish") { await regSave(); return; }
  if (a === "reg-edit") { const p = App.profile; UI.reg = { ...newReg(), step: 2, edit: true, acc: { ...p.account }, co: { ...p.company }, fromKeys: p.company?.from_base || [], from: p.company?.base_id ? { id: p.company.base_id, name: App.C[p.company.base_id]?.name, egr: egrulSrc(App.C[p.company.base_id]) } : null }; render(); window.scrollTo(0, 0); return; }
  if (a === "reg-cancel") { UI.reg = null; render(); return; }
  const ch = t.dataset.chain;
  switch (a) {
    case "filters-open": $("#filters")?.classList.add("open"); break;
    case "filters-close": $("#filters")?.classList.remove("open"); break;
    case "reset-companies": UI.companies.f = {}; UI.companies.q = ""; UI.companies.page = 1; render(); break;
    case "reset-sf": UI.sf = { hide: [], cities: [], noRisk: false, site: false }; render(); break;
    case "reset-products": UI.products.f = {}; UI.products.q = ""; UI.products.page = 1; render(); break;
    case "ai-parse": { const v = $("#sq")?.value.trim(); if (v) runSearch(v, true); else toast("Введите запрос."); break; }
    case "save-search": if (UI.lastQuery) { App.profile.saved.unshift({ text: UI.lastQuery.raw, at: nowIso() }); await Store.saveProfile(); toast("Поиск сохранён в личном кабинете."); } break;
    case "saved-run": runSearch(App.profile.saved[Number(t.dataset.i)].text, false); break;
    case "saved-del": App.profile.saved.splice(Number(t.dataset.i), 1); await Store.saveProfile(); rerender(); break;
    case "compare-results": UI.lastResults.slice(0, 4).forEach((m) => { if (!App.profile.compare.includes("c:" + m.c.id)) App.profile.compare.push("c:" + m.c.id); }); App.profile.compare = App.profile.compare.slice(-4); await Store.saveProfile(); location.hash = "#compare"; break;
    case "compare-clear": App.profile.compare = []; await Store.saveProfile(); rerender(); break;
    case "rfq": { const p = t.dataset.product ? App.P[t.dataset.product] : null; const cid = t.dataset.company || p?.company_id; openRequestForm({ target_company: cid, target_product: p?.id || "", what: p ? p.name : "", okpd2: p?.okpd2?.code || "" }); break; }
    case "rfq-offer": { const o = App.offers.find((x) => x.id === t.dataset.id); openRequestForm({ target_company: o?.company_id || "", what: o?.title || "", okpd2: o?.okpd2 || "", unit: o?.unit }); break; }
    case "to-request": { const p = App.P[t.dataset.product]; openRequestForm({ what: p.name, okpd2: p.okpd2?.code || "" }); break; }
    case "to-chain": addToChainPanel(t.dataset.company, t.dataset.product); break;
    case "offer-new": openOfferForm(); break;
    case "offer-open": offerDetails(t.dataset.id); break;
    case "offer-del": await Store.del("offers", t.dataset.id); closePanel(); toast("Предложение снято с публикации."); break;
    case "request-new": openRequestForm(); break;
    case "request-del": await Store.del("requests", t.dataset.id); location.hash = "#buy"; toast("Заявка закрыта."); break;
    case "report": openPanel(`<div class="panel-h"><div><div class="label">Сообщить об ошибке</div><h2 class="h2">${esc(App.C[t.dataset.company].short)}</h2></div><button class="x" data-close aria-label="Закрыть">×</button></div>
      <form id="report-form" class="form" data-company="${t.dataset.company}"><div class="field full"><label for="rp-f">Поле</label><input class="inp" id="rp-f" name="field" placeholder="например: адрес"></div><div class="field full"><label for="rp-t">Что неверно и где подтверждение *</label><textarea class="inp" id="rp-t" name="text" required></textarea></div><div class="full"><button class="btn pri" type="submit">Отправить</button></div></form>`, "narrow"); break;
    case "report-close": await Store.del("reports", t.dataset.id); break;
    case "recrawl": await Store.put("reports", "q-" + uidGen(), { kind: "recrawl", url: t.dataset.url, author: App.uid, created_at: nowIso() }); toast("Задача повторного обхода поставлена в очередь."); break;
    case "unclaim": App.profile.companies = App.profile.companies.filter((x) => x.company_id !== t.dataset.id); await Store.saveProfile(); rerender(); break;
    case "wh-del": App.profile.warehouses = App.profile.warehouses.filter((x) => x.id !== t.dataset.id); await Store.saveProfile(); rerender(); break;
    case "chain-example": { const c = exampleChain(); await Store.saveChain(c); location.hash = "#ch." + c.id; toast("Создана цепочка из примера. Связи помечены как выводы системы."); break; }
    case "chain-new": { const c = { id: "chain-" + uidGen(), title: "Новая цепочка", buyer_city: App.profile.city, nodes: [], edges: [], created_at: nowIso() }; await Store.saveChain(c); location.hash = "#ch." + c.id; setTimeout(() => nodeEditPanel(c.id, null), 50); break; }
    case "chain-del": await Store.delChain(ch); location.hash = "#chains"; break;
    case "chain-rename": openPanel(`<div class="panel-h"><h2 class="h2">Название цепочки</h2><button class="x" data-close aria-label="Закрыть">×</button></div><form id="rename-form" class="form" data-chain="${ch}"><div class="field full"><label for="rn-t">Название</label><input class="inp" id="rn-t" name="title" required value="${esc(App.chains.find((c) => c.id === ch).title)}"></div><div class="full"><button class="btn pri" type="submit">Сохранить</button></div></form>`, "narrow"); break;
    case "node-add": nodeEditPanel(ch, null); break;
    case "node-edit": nodeEditPanel(ch, t.dataset.node); break;
    case "node-del": { const c = JSON.parse(JSON.stringify(App.chains.find((x) => x.id === ch))); const i = c.nodes.findIndex((n) => n.id === t.dataset.node); c.nodes.splice(i, 1); c.edges = c.nodes.slice(1).map((nd, k) => edgeFor(c, c.nodes[k].id, nd.id) || { from: c.nodes[k].id, to: nd.id, type: relType(c.nodes[k], nd) }); await Store.saveChain(c); break; }
    case "edge-edit": edgeEditPanel(ch, t.dataset.from, t.dataset.to); break;
    case "declined": { const c = JSON.parse(JSON.stringify(App.chains.find((x) => x.id === ch))); c.nodes.find((n) => n.id === t.dataset.node).status = "DECLINED"; await Store.saveChain(c); openReplace(ch, t.dataset.node); break; }
    case "replace": openReplace(ch, t.dataset.node); break;
    case "pick": await pickSupplier(ch, t.dataset.node, t.dataset.company, t.dataset.product); break;
    case "repl-request": { const c = App.chains.find((x) => x.id === ch), nd = c.nodes.find((n) => n.id === t.dataset.node); openRequestForm({ what: nd.req_text || (nd.product_id ? App.P[nd.product_id].name : nd.step) }); break; }
    case "menu": $("#drawer").classList.toggle("open"); break;
  }
});

/* ---------- Изменения полей: фильтры, сортировка, переключатели ---------- */
document.addEventListener("change", async (e) => {
  const t = e.target;
  // Регистрация: галочки согласия и проверки данных
  if (t.dataset.rchk) { UI.reg[t.dataset.rchk] = t.checked; delete UI.reg.errors[t.dataset.rchk]; t.closest(".has-err")?.classList.remove("has-err"); return; }
  // Уведомления: канал вкл/выкл, контакт, события
  if (t.dataset.nch || t.dataset.ncontact || t.dataset.nev) {
    const n = App.profile.notify || (App.profile.notify = defaultNotify());
    if (t.dataset.nch) { n.channels[t.dataset.nch].on = t.checked; toast((t.checked ? "Включены" : "Выключены") + " уведомления: " + (t.dataset.nch === "vk" ? "ВКонтакте" : "Telegram")); }
    if (t.dataset.ncontact) { const v = notifyContact(t.dataset.ncontact, t.value); if (v === null) { toast("Не удалось распознать контакт. Проверьте формат."); return; } n.channels[t.dataset.ncontact].contact = v; toast("Контакт сохранён"); }
    if (t.dataset.nev) { const [ev, ch] = t.dataset.nev.split(":"); n.events[ev][ch] = t.checked; }
    await Store.saveProfile(); render(); return;
  }
  if (t.id === "show-unv") { App.showUnverified = t.checked; if (UI.lastQuery) UI.lastResults = searchCompanies(UI.lastQuery, { includeUnverified: App.showUnverified }); UI.companies.page = UI.products.page = 1; render(); return; }
  if (t.dataset.f) { const [k, f] = t.dataset.f.split(":"); UI[k].f[f] = t.value; UI[k].page = 1; render(); return; }
  if (t.dataset.fs) { const h = UI.companies.f.hide || (UI.companies.f.hide = []); if (t.checked) UI.companies.f.hide = h.filter((x) => x !== t.dataset.fs); else h.push(t.dataset.fs); UI.companies.page = 1; render(); return; }
  if (t.dataset.fb) { UI.companies.f[t.dataset.fb] = t.checked; UI.companies.page = 1; render(); return; }
  if (t.dataset.sfHide) { const k = t.dataset.sfHide; UI.sf.hide = t.checked ? UI.sf.hide.filter((x) => x !== k) : [...UI.sf.hide, k]; render(); return; }
  if (t.dataset.sfCity) { const k = t.dataset.sfCity; UI.sf.cities = t.checked ? UI.sf.cities.filter((x) => x !== k) : [...UI.sf.cities, k]; render(); return; }
  if (t.dataset.sf) { UI.sf[t.dataset.sf] = t.checked; render(); return; }
  if (t.dataset.fb2) { UI.products.f[t.dataset.fb2] = t.checked; UI.products.page = 1; render(); return; }
  if (t.dataset.sort) { if (t.dataset.sort === "search") UI.searchSort = t.value; else { UI[t.dataset.sort].sort = t.value; UI[t.dataset.sort].page = 1; } render(); return; }
  if (t.dataset.srcflag) { await Store.put("sourceflags", t.dataset.srcflag, { disabled: !t.checked, at: nowIso() }); audit(`Источник ${App.S[t.dataset.srcflag].source_title} (${App.C[App.S[t.dataset.srcflag].company_id].short}) ${t.checked ? "включён" : "отключён"}`); return; }
  if (t.dataset.setstatus) { const c = App.C[t.dataset.setstatus]; await Store.put("reports", "s-" + uidGen(), { kind: "override", company_id: c.id, status: t.value, author: App.uid, created_at: nowIso() }); audit(`Статус ${c.short}: ${c.verification_status} → ${t.value}`); return; }
});

/* ---------- Живой поиск по каталогам с задержкой ввода ---------- */
let _qt = 0;
document.addEventListener("input", (e) => {
  const t = e.target;
  // Регистрация: ввод полей без перерисовки и подсказки по названию компании
  if (t.dataset.rf) { const [sc, k] = t.dataset.rf.split("."); UI.reg[sc][k] = t.value; return; }
  if (t.dataset.rq) { const ul = $("#rg-sugg"); if (ul) ul.innerHTML = regSuggestHtml(regSuggest(t.value)); return; }
  if (!t.dataset.q) return;
  clearTimeout(_qt); _qt = setTimeout(() => { UI[t.dataset.q].q = t.value; UI[t.dataset.q].page = 1; render(); }, 250);
});

/* ---------- Запуск: загрузка базы и первая отрисовка ---------- */
async function boot() {
  try {
    const r = await fetch("data.json", { cache: "no-cache" });
    indexData(await r.json());
  } catch (e) {
    $("#app").innerHTML = `<div class="wrap page"><div class="note warn">Не удалось загрузить базу данных платформы. Обновите страницу.</div></div>`; return;
  }
  render();
  await Store.init();
  render();
}
boot();
