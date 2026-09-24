/* ===== Ядро: данные, хранилище, утилиты ===== */
"use strict";
const App = {
  data: null,          // проверенная база (data.json из Git-репозитория данных)
  C: {},               // companies by id
  P: {},               // products by id
  S: {},               // sources by id
  uid: null,           // id зрителя
  canEdit: false,
  mode: "local",       // "db" | "local"
  offers: [], requests: [], reports: [], srcflags: {},
  profile: { favorites: [], compare: [], saved: [], city: "Волгоград", companies: [], warehouses: [] },
  chains: [],
  sample: null,
  showUnverified: false,
};
const TODAY = "2026-09-24";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const uidGen = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
const fmtDate = (d) => { if (!d) return ""; const [y, m, dd] = String(d).slice(0, 10).split("-"); return `${dd}.${m}.${y}`; };
const nowIso = () => new Date().toISOString();
const plural = (n, a, b, c) => { const m10 = n % 10, m100 = n % 100; return m10 === 1 && m100 !== 11 ? a : m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? b : c; };

function toast(msg) {
  const t = document.createElement("div"); t.className = "toast"; t.setAttribute("role", "status"); t.textContent = msg;
  document.body.appendChild(t); setTimeout(() => t.remove(), 3200);
}

/* ---- Локальное хранилище (fallback, когда db недоступна) ---- */
const LS = {
  get(k, d) { try { const v = localStorage.getItem("pk:" + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem("pk:" + k, JSON.stringify(v)); } catch (e) {} },
};

/* ---- Слой хранения: db-капабилити или localStorage ---- */
const Store = {
  db: null,
  async init() {
    let user = null;
    try { user = await window.claude?.use?.("user"); } catch (e) {}
    try { this.db = await window.claude?.use?.("db"); } catch (e) { this.db = null; }
    try { App.sample = await window.claude?.use?.("sample"); } catch (e) { App.sample = null; }
    if (user) {
      try { App.uid = await user.id(); } catch (e) {}
      try { App.canEdit = !!user.canEdit(); } catch (e) {}
      Store.user = user;
    }
    if (this.db && App.uid) {
      App.mode = "db";
      this.sub("offers", (rows) => { App.offers = rows; rerender(); });
      this.sub("requests", (rows) => { App.requests = rows; rerender(); });
      this.sub("reports", (rows) => { App.reports = rows; rerender(); });
      this.sub("sourceflags", (rows) => { App.srcflags = Object.fromEntries(rows.map((r) => [r.id, r])); rerender(); });
      try {
        this.db.collection("data/users/" + App.uid).onSnapshot((snap) => {
          const docs = snap.docs.map((d) => ({ id: d.id, ...d.data() }));
          const prof = docs.find((d) => d.id === "profile");
          if (prof) App.profile = Object.assign({ favorites: [], compare: [], saved: [], city: "Волгоград", companies: [], warehouses: [] }, prof);
          App.chains = docs.filter((d) => d.kind === "chain").sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
          rerender();
        }, () => {});
      } catch (e) {}
    } else {
      App.mode = "local"; App.uid = App.uid || "local";
      App.offers = LS.get("offers", []); App.requests = LS.get("requests", []); App.reports = LS.get("reports", []);
      App.srcflags = LS.get("sourceflags", {}); App.chains = LS.get("chains", []);
      App.profile = Object.assign(App.profile, LS.get("profile", {}));
      App.canEdit = true;
    }
  },
  sub(coll, cb) {
    try {
      this.db.collection(coll).limit(500).onSnapshot((snap) => cb(snap.docs.map((d) => ({ id: d.id, ...d.data() }))), () => {});
    } catch (e) {}
  },
  async put(coll, id, obj) {
    if (App.mode === "db") {
      try { await this.db.collection(coll).doc(id).set(obj); return true; }
      catch (e) { toast(e?.code === "quota_exceeded" ? "Хранилище заполнено — удалите старые записи." : "Не удалось сохранить. Повторите попытку."); return false; }
    }
    const key = coll === "sourceflags" ? "sourceflags" : coll;
    if (coll === "sourceflags") { App.srcflags[id] = { id, ...obj }; LS.set(key, App.srcflags); }
    else { const arr = App[coll] || []; const i = arr.findIndex((x) => x.id === id); const row = { id, ...obj }; if (i >= 0) arr[i] = row; else arr.unshift(row); App[coll] = arr; LS.set(key, arr); }
    rerender(); return true;
  },
  async del(coll, id) {
    if (App.mode === "db") { try { await this.db.collection(coll).doc(id).delete(); } catch (e) { toast("Не удалось удалить."); } return; }
    App[coll] = (App[coll] || []).filter((x) => x.id !== id); LS.set(coll, App[coll]); rerender();
  },
  async saveProfile() {
    if (App.mode === "db") { try { await this.db.doc("data/users/" + App.uid + "/profile").set({ ...App.profile }); } catch (e) { toast("Профиль не сохранён."); } }
    else LS.set("profile", App.profile);
  },
  async saveChain(ch) {
    ch.updated_at = nowIso(); ch.kind = "chain";
    if (App.mode === "db") { try { await this.db.doc("data/users/" + App.uid + "/" + ch.id).set(JSON.parse(JSON.stringify(ch))); } catch (e) { toast("Цепочка не сохранена."); } }
    else { const i = App.chains.findIndex((c) => c.id === ch.id); if (i >= 0) App.chains[i] = ch; else App.chains.unshift(ch); LS.set("chains", App.chains); }
    rerender();
  },
  async delChain(id) {
    if (App.mode === "db") { try { await this.db.doc("data/users/" + App.uid + "/" + id).delete(); } catch (e) {} }
    else { App.chains = App.chains.filter((c) => c.id !== id); LS.set("chains", App.chains); }
    rerender();
  },
};

/* ---- Индексация проверенной базы ---- */
function indexData(d) {
  App.data = d;
  for (const c of d.companies) {
    App.C[c.id] = c;
    for (const s of c.sources) App.S[s.id] = { ...s, company_id: c.id };
    for (const p of c.products) App.P[p.id] = { ...p, company_id: c.id };
  }
}
const regionName = (code) => App.data.regions[code]?.name || "Не указано";
const srcActive = (id) => !(App.srcflags[id] && App.srcflags[id].disabled);

/* Полнота профиля: сколько ключевых полей подтверждено источником (это не рейтинг) */
const PROFILE_FIELDS = [
  ["inn", "ИНН"], ["ogrn", "ОГРН"], ["address", "Адрес"], ["site", "Сайт"], ["phones", "Телефон"], ["emails", "E-mail"],
  ["okved_main", "Основной ОКВЭД"], ["products", "Продукция"], ["technologies", "Технологии"], ["materials", "Материалы"],
  ["capacities", "Мощности"], ["certificates", "Сертификаты"], ["sites", "Площадки"],
];
function completeness(c) {
  let n = 0; for (const [k] of PROFILE_FIELDS) { const v = c[k]; if (Array.isArray(v) ? v.length : v) n++; }
  return { n, of: PROFILE_FIELDS.length };
}

/* Расстояние по прямой между центрами городов (км) */
function distanceKm(cityA, cityB) {
  const A = App.data.cities[cityA], B = App.data.cities[cityB];
  if (!A || !B) return null;
  const R = 6371, toR = (x) => (x * Math.PI) / 180;
  const dLat = toR(B[0] - A[0]), dLon = toR(B[1] - A[1]);
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(toR(A[0])) * Math.cos(toR(B[0])) * Math.sin(dLon / 2) ** 2;
  return Math.round(2 * R * Math.asin(Math.sqrt(a)));
}
function distTxt(d, from) {
  if (d == null) return "";
  return d === 0 ? "в том же городе" : `${d} км по прямой от г. ${from}`;
}

/* ---- UI-атомы ---- */
const STATUS_TXT = { VERIFIED: "✓ Подтверждено", PARTIALLY_VERIFIED: "◐ Частично подтверждено", UNVERIFIED: "○ Не подтверждено", OUTDATED: "! Устарело", USER: "Указано пользователем" };
const statusBadge = (st) => `<span class="st ${st}" title="${st}">${STATUS_TXT[st] || st}</span>`;
const unk = (kind = "none") => ({
  none: '<span class="unk">Нет открытых данных</span>',
  na: '<span class="unk">Не указано</span>',
  price: '<span class="unk req">Цена по запросу</span>',
  conf: '<span class="unk conf">Требует подтверждения</span>',
}[kind]);
function okvedTag(code, withName) {
  if (!code) return unk("none");
  const nm = App.data.okved[code] || "";
  return `<span class="code okved" title="${esc(nm)}"><b>ОКВЭД</b><span>${esc(code)}</span></span>${withName && nm ? ` <span class="muted">${esc(nm)}</span>` : ""}`;
}
function okpdTag(o, withName) {
  if (!o) return '<span class="unk">ОКПД2 не указан в источнике</span>';
  const inf = o.status === "INFERRED";
  return `<span class="code okpd2 ${inf ? "inf" : ""}" title="${esc(o.name)}${inf ? " — присвоено по классификатору, требует подтверждения" : ""}"><b>ОКПД2${inf ? " · присвоено" : ""}</b><span>${esc(o.code)}</span></span>${withName ? ` <span class="muted">${esc(o.name)}</span>` : ""}`;
}
const srcBtn = (id, label = "Источник") => id ? `<button class="srcbtn" data-src="${esc(id)}">${esc(label)}</button>` : "";
const domain = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return u; } };
const userTag = () => `<span class="st USER">Указано пользователем · не проверено</span>`;
function priceHtml(price) {
  if (!price || price.value == null || price.value === "") return unk("price");
  return `<b class="num">${esc(Number(price.value).toLocaleString("ru-RU"))} ${esc(price.currency || "₽")}</b> / ${esc(price.unit || "ед.")} <span class="muted">· цена указана продавцом${price.date ? ", " + fmtDate(price.date) : ""}</span>`;
}

/* Окно «Источник данных» */
function openSource(id) {
  const s = App.S[id]; if (!s) return;
  const c = App.C[s.company_id];
  const disc = (c.discrepancies || []).filter((d) => (d.values || []).some((v) => v.source_id === id));
  openPanel(`<div class="panel-h"><div><div class="label">Источник данных</div><h2 class="h2">${esc(s.source_title)}</h2></div><button class="x" data-close aria-label="Закрыть">×</button></div>
  <dl class="kv">
    <dt>Предприятие</dt><dd><a href="#c.${c.id}" data-close>${esc(c.name)}</a></dd>
    <dt>URL</dt><dd><a href="${esc(s.source_url)}" target="_blank" rel="noopener">${esc(s.source_url)}</a></dd>
    <dt>Тип источника</dt><dd><span class="code okved"><span>${esc(s.source_type)}</span></span> · приоритет ${s.priority} из 12</dd>
    <dt>Подтверждает</dt><dd>${s.confirms?.length ? esc(s.confirms.join(", ")) : '<span class="unk">Параметры не подтверждены — источник не прочитан</span>'}</dd>
    <dt>Дата публикации</dt><dd>${s.source_date ? fmtDate(s.source_date) : unk("na")}</dd>
    <dt>Проверено</dt><dd>${fmtDate(s.last_verified_at)}</dd>
    <dt>Результат обхода</dt><dd>${s.fetch_status === "OK" ? '<span class="v yes">Прочитан</span>' : `<span class="v no">${esc(s.fetch_status)}</span>`}</dd>
    ${s.note ? `<dt>Примечание</dt><dd>${esc(s.note)}</dd>` : ""}
    <dt>Статус в системе</dt><dd>${srcActive(id) ? "Используется" : '<span class="v no">Отключён администратором</span>'}</dd>
  </dl>
  ${disc.length ? `<div class="sec" style="margin-top:24px"><div class="label">Расхождения с другими источниками</div>${disc.map((d) => `<div class="note warn" style="margin-top:8px"><b>${esc(d.field)}.</b> ${d.values.map((v) => `${esc(v.value)} <span class="muted">(${esc(App.S[v.source_id]?.source_title || v.source_id)})</span>`).join("; ")}<br>${esc(d.note)}</div>`).join("")}</div>` : ""}
  <p class="muted" style="margin-top:24px">Порядок приоритета: официальный сайт → каталог → документы предприятия → госреестры → ФНС/ЕГРЮЛ → ГИСП → органы власти → региональные каталоги → ТПП → центры поддержки экспорта → отраслевые каталоги → прочие.</p>`, "narrow");
}

/* Панель поверх страницы */
function openPanel(html, cls = "") {
  closePanel();
  const o = document.createElement("div"); o.className = "ovl"; o.id = "ovl";
  o.innerHTML = `<div class="panel ${cls}" role="dialog" aria-modal="true">${html}</div>`;
  o.addEventListener("click", (e) => { if (e.target === o || e.target.closest("[data-close]")) closePanel(); });
  document.body.appendChild(o);
  const f = o.querySelector("input,select,textarea,button"); f && f.focus();
}
function closePanel() { $("#ovl")?.remove(); }
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closePanel(); });
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-src]"); if (b) { e.preventDefault(); openSource(b.dataset.src); }
});

/* Избранное / сравнение */
function toggleList(key, id) {
  const arr = App.profile[key] || (App.profile[key] = []);
  const i = arr.indexOf(id);
  if (i >= 0) arr.splice(i, 1); else { if (key === "compare" && arr.length >= 4) { toast("В сравнении не больше 4 позиций."); return; } arr.push(id); }
  Store.saveProfile(); rerender();
  toast(key === "compare" ? (i >= 0 ? "Убрано из сравнения" : "Добавлено в сравнение") : (i >= 0 ? "Убрано из избранного" : "Добавлено в избранное"));
}
