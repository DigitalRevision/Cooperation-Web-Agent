/* ===== Ядро: данные, хранилище, утилиты ===== */
"use strict";

/* ---- Глобальное состояние приложения ---- */
const App = {
  data: null,          // проверенная база (data.json из Git-репозитория данных)
  C: {},               // companies by id
  P: {},               // products by id
  S: {},               // sources by id
  uid: null,           // id зрителя
  canEdit: false,
  mode: "local",       // "db" | "local"
  offers: [], requests: [], responses: [], reports: [], srcflags: {},
  // модерация: регистрации представителей, решения модератора, подтверждённые представители, смена статуса проверки
  registrations: [], moderation: [], reps: [], overrides: [], decisions: [], product_edits: [],
  profile: { favorites: [], compare: [], saved: [], city: "Волгоград", companies: [], warehouses: [] },
  chains: [],
  sample: null,
  showUnverified: false,
};

/* ---- Базовые утилиты: выборка DOM, экранирование, даты, склонения ---- */
const TODAY = "2026-09-24";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const uidGen = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
// Дата ГГГГ-ММ-ДД → ДД.ММ.ГГГГ; результат экранирован, дата может прийти из пользовательской записи
const fmtDate = (d) => { if (!d) return ""; const [y, m, dd] = String(d).slice(0, 10).split("-"); return esc(`${dd}.${m}.${y}`); };
const nowIso = () => new Date().toISOString();
const plural = (n, a, b, c) => { const m10 = n % 10, m100 = n % 100; return m10 === 1 && m100 !== 11 ? a : m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20) ? b : c; };

// Всплывающее уведомление внизу экрана
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
      this.sub("responses", (rows) => { App.responses = rows; rerender(); });
      this.sub("reports", (rows) => { App.reports = rows; rerender(); });
      this.sub("sourceflags", (rows) => { App.srcflags = Object.fromEntries(rows.map((r) => [r.id, r])); rerender(); });
      // Правила доступа (README, «Публикация на claude.ai»): регистрации и решения модератора видят только сам пользователь
      // и модераторы; документы, которые зрителю не видны, просто не попадают в выборку
      for (const coll of ["registrations", "moderation", "reps", "overrides", "decisions", "product_edits"]) this.sub(coll, (rows) => { App[coll] = rows; rerender(); });
      try {
        this.db.collection("data/users/" + App.uid).onSnapshot((snap) => {
          const docs = snap.docs.map((d) => ({ id: d.id, ...d.data() }));
          const prof = docs.find((d) => d.id === "profile");
          if (prof) { App.profile = Object.assign({ favorites: [], compare: [], saved: [], city: "Волгоград", companies: [], warehouses: [] }, prof); ensureRegistrationSubmitted(); }
          App.chains = docs.filter((d) => d.kind === "chain").sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
          rerender();
        }, () => {});
      } catch (e) {}
    } else {
      App.mode = "local"; App.uid = App.uid || "local";
      App.offers = LS.get("offers", []); App.requests = LS.get("requests", []); App.responses = LS.get("responses", []); App.reports = LS.get("reports", []);
      for (const coll of ["registrations", "moderation", "reps", "overrides", "decisions", "product_edits"]) App[coll] = LS.get(coll, []);
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

/* Отклики на заявку. Каждый отклик — отдельная запись коллекции responses: откликающийся не перезаписывает документ заявки,
   и одновременные отклики не теряются. Старые отклики внутри заявки (поле responses) тоже показываются.
   key — постоянный ключ отклика для ленты уведомлений. */
function responsesOf(r) {
  const legacy = (r.responses || []).map((x, i) => ({ ...x, key: r.id + ":" + i }));
  const own = App.responses.filter((x) => x.request_id === r.id).map((x) => ({ ...x, key: x.id }));
  return [...legacy, ...own].sort((a, b) => String(a.at || "").localeCompare(String(b.at || "")));
}

/* ---- Вход в личный кабинет и модерация представителя ---- */
// Зарегистрирован и не вышел из кабинета
const loggedIn = () => !!App.profile.account && !App.profile.signedOut;
// Предприятия пользователя: из регистрации и привязанные в кабинете.
// Их собственные позиции не показываются пользователю в «Предложениях поставщиков»
function myCompanyIds() {
  if (!loggedIn()) return new Set();
  return new Set([App.profile.company?.base_id, ...(App.profile.companies || []).map((x) => x.company_id)].filter(Boolean));
}
// Решение модератора по текущей отправке регистрации; null — ещё не рассмотрена
function decisionFor(reg) {
  const m = reg && App.moderation.find((x) => x.id === reg.id);
  return m && m.submitted_at === reg.submitted_at ? m : null;
}
// Автор подтверждён модератором как представитель этого предприятия
const isVerifiedRep = (uid, companyId) => !!companyId && App.reps.some((r) => r.id === uid && r.company_id === companyId);

// Своя позиция: продукция предприятия пользователя или его собственная запись. Запрашивать предложение у себя нельзя
const isMine = (companyId, author) => (!!companyId && myCompanyIds().has(companyId)) || (!!author && author === App.uid && loggedIn());
// Изменять и удалять продукцию из открытых источников может только подтверждённый модератором представитель этого предприятия
const canEditProducts = (companyId) => loggedIn() && isVerifiedRep(App.uid, companyId);

/* ---- Правки продукции представителями предприятий поверх открытых источников ---- */
// Документ product_edits/<uid> = { items: { <id позиции>: { deleted, fields, updated_at } } } пишет только сам пользователь.
// Применяются лишь правки подтверждённого представителя того предприятия, чья это продукция (отметки reps пишет только модератор).
// Исходные данные из открытых источников не меняются: удалённую позицию можно вернуть
const PRODUCT_FIELDS = ["name", "kind", "category", "description", "params", "okpd2"];
function applyProductEdits() {
  const byCompany = {};
  for (const doc of App.product_edits) {
    const rep = App.reps.find((r) => r.id === doc.id); if (!rep) continue;
    const mine = byCompany[rep.company_id] || (byCompany[rep.company_id] = {});
    for (const [pid, e] of Object.entries(doc.items || {})) if (!mine[pid] || (e.updated_at || "") > (mine[pid].updated_at || "")) mine[pid] = e;
  }
  for (const c of App.data.companies) {
    if (!c._origProducts) c._origProducts = c.products;
    const ed = byCompany[c.id] || {};
    c._deleted = c._origProducts.filter((p) => ed[p.id]?.deleted);
    c.products = c._origProducts.filter((p) => !ed[p.id]?.deleted).map((p) => {
      const f = ed[p.id]?.fields; if (!f) return p;
      return { ...p, ...Object.fromEntries(PRODUCT_FIELDS.filter((k) => k in f).map((k) => [k, f[k]])), company_edit: { at: ed[p.id].updated_at } };
    });
    for (const p of c._origProducts) delete App.P[p.id];
    for (const p of c.products) App.P[p.id] = { ...p, company_id: c.id };
  }
}
// Своя правка пользователя по позиции (для формы и восстановления)
const myProductEdit = (pid) => (App.product_edits.find((d) => d.id === App.uid)?.items || {})[pid];
async function saveProductEdit(pid, patch) {
  const doc = App.product_edits.find((d) => d.id === App.uid) || { items: {} };
  const items = { ...(doc.items || {}), [pid]: { ...(doc.items || {})[pid], ...patch, updated_at: nowIso() } };
  return Store.put("product_edits", App.uid, { company_id: App.P[pid]?.company_id || doc.company_id || null, items });
}

/* ---- Модерация предложений и заявок ---- */
// Решение модератора: документ decisions/<offers|requests>:<id>, записывать его может только модератор.
// Старая отметка status внутри самой записи учитывается только на этом устройстве: в общем хранилище её мог поставить кто угодно
function itemDecision(coll, item) {
  const d = App.decisions.find((x) => x.id === coll + ":" + item.id);
  if (d) return d;
  return App.mode === "local" && ["APPROVED", "REJECTED"].includes(item.status) ? { status: item.status, comment: "", decided_at: item.created_at, legacy: true } : null;
}
// Отклонённые модератором записи видит только их автор
const shownToAll = (coll) => App[coll].filter((x) => itemDecision(coll, x)?.status !== "REJECTED" || x.author === App.uid);
// Пометка записи: отклонена, от подтверждённого представителя, проверена модератором или указана пользователем
function itemTag(coll, x) {
  const d = itemDecision(coll, x);
  if (d?.status === "REJECTED") return `<span class="st OUTDATED" title="${esc(d.comment || "")}">Отклонено модератором</span>`;
  if (coll === "offers" && isVerifiedRep(x.author, x.company_id)) return `<span class="st VERIFIED" title="Модератор подтвердил, что автор представляет эту компанию">Представитель компании подтверждён</span>`;
  if (d?.status === "APPROVED") return `<span class="st VERIFIED" title="Модератор проверил запись">Проверено модератором</span>`;
  return userTag();
}
// Причина отклонения — только автору, под записью
function rejectNote(coll, x) {
  const d = itemDecision(coll, x);
  return d?.status === "REJECTED" && x.author === App.uid
    ? `<div class="note warn" style="margin-top:8px">Модератор отклонил ${coll === "offers" ? "предложение" : "заявку"}${d.comment ? `: ${esc(d.comment)}` : "."} Другие пользователи ${coll === "offers" ? "его" : "её"} не видят.</div>` : "";
}

/* ---- Индексация проверенной базы ---- */
function indexData(d) {
  App.data = d;
  for (const c of d.companies) {
    App.C[c.id] = c;
    for (const s of c.sources) App.S[s.id] = { ...s, company_id: c.id };
    for (const p of c.products) App.P[p.id] = { ...p, company_id: c.id };
  }
}
// Название региона по коду и проверка, не отключён ли источник
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
// Текст расстояния для карточек («120 км от г. …»)
function distTxt(d, from) {
  if (d == null) return "";
  return d === 0 ? "в том же городе" : `${d} км по прямой от г. ${from}`;
}

/* ---- UI-атомы ---- */
const STATUS_TXT = { VERIFIED: "✓ Подтверждено", PARTIALLY_VERIFIED: "◐ Частично подтверждено", UNVERIFIED: "○ Не подтверждено", OUTDATED: "! Устарело", USER: "Указано пользователем" };
// Статус проверки данных простыми словами: подпись без значка и пояснение, что он значит
const STATUS_LABEL = { VERIFIED: "Подтверждено", PARTIALLY_VERIFIED: "Частично подтверждено", UNVERIFIED: "Не подтверждено", OUTDATED: "Устарело" };
const STATUS_HINT = {
  VERIFIED: "Данные официального сайта совпадают с реестром ФНС",
  PARTIALLY_VERIFIED: "Реквизиты из реестра ФНС, но сайт не прочитан или есть расхождения",
  UNVERIFIED: "Реквизиты не найдены, в основном поиске не участвует",
  OUTDATED: "Юрлицо ликвидировано, в поиске не показывается",
  USER: "Данные внёс пользователь, модератор их ещё не проверил",
};
const statusBadge = (st) => `<span class="st ${esc(st)}" title="${esc(STATUS_HINT[st] || "")}">${esc(STATUS_TXT[st] || st)}</span>`;
// Типы источников и результат обхода простыми словами
const SOURCE_TYPE_TXT = { OFFICIAL_SITE: "Официальный сайт", OFFICIAL_CATALOG: "Каталог предприятия", FNS_EGRUL: "ЕГРЮЛ ФНС", FNS_PB: "«Прозрачный бизнес» ФНС",
  FNS_GIRBO: "Бухгалтерская отчётность (ГИР БО)", FNS_OPENDATA: "Открытые данные ФНС", EFRSB: "Федресурс (банкротства)", EGRUL_AGGREGATOR: "Выписка ЕГРЮЛ (агрегатор)",
  CHECKO: "Checko: суды и ФССП", GISP: "ГИСП Минпромторга", INDUSTRY_CATALOG: "Отраслевой каталог", REGIONAL_CATALOG: "Региональный каталог", OTHER: "Прочий источник" };
const sourceTypeTxt = (t) => SOURCE_TYPE_TXT[t] || t;
function fetchTxt(st) {
  if (st === "OK") return "Прочитан";
  const http = /^HTTP_(\d+)$/.exec(st || "");
  if (http) return `${{ 401: "Нужна авторизация", 403: "Доступ запрещён", 404: "Страница не найдена" }[http[1]] || "Ошибка сайта"} (${http[1]})`;
  return { REDIRECT_LOOP: "Сайт зациклил перенаправления", ROBOTS_UNAVAILABLE: "Сайт не отдал правила обхода", OFFSITE_REDIRECT: "Перенаправил на чужой сайт", FAILED: "Не ответил" }[st] || st || "Нет данных";
}
// Статус записи на модерации (предложения, заявки)
const MOD_TXT = { NEW: "Ожидает проверки", APPROVED: "Одобрено", REJECTED: "Отклонено" };

/* ---- Телефоны: +7 (XXX) XXX-XX-XX; для городских номеров выделяется код города ---- */
// Коды городов длиннее трёх цифр, встречающиеся в регионах базы; остальные номера делятся как 3 + 7
const AREA_CODES = ["84457", "84442", "84463", "84465", "84472", "48677", "8442", "8443", "8452", "8453", "8512", "8634", "8636", "8639", "4862"];
// Возвращает { text, tel } или null, если строка не похожа на российский номер. Пояснение в скобках сохраняется: «(отдел продаж)»
function parsePhone(raw) {
  const s = String(raw || "").trim();
  // номер — от начала строки до последней цифры; дальше пояснение
  const m = /^(\+?[\d\s()\-.]*\d)(.*)$/.exec(s);
  if (!m) return null;
  let d = m[1].replace(/\D/g, "");
  if (d.length === 10) d = "7" + d;
  if (d.length !== 11 || !/^[78]/.test(d)) return null;
  d = "7" + d.slice(1);
  const rest = d.slice(1), code = AREA_CODES.find((c) => rest.startsWith(c)) || rest.slice(0, 3), sub = rest.slice(code.length);
  const parts = sub.length === 7 ? [sub.slice(0, 3), sub.slice(3, 5), sub.slice(5)] : sub.length === 6 ? [sub.slice(0, 2), sub.slice(2, 4), sub.slice(4)] : [sub.slice(0, 1), sub.slice(1, 3), sub.slice(3)];
  return { text: `+7 (${code}) ${parts.join("-")}`, tel: "+" + d, note: m[2].trim() };
}
// Номер для хранения: в едином формате, с пояснением; нераспознанную строку оставляем как есть
const fmtPhone = (raw) => { const p = parsePhone(raw); return p ? (p.text + (p.note ? " " + p.note : "")) : String(raw || "").trim(); };
// Номер для показа: ссылка для звонка с телефона
function phoneHtml(raw) {
  const p = parsePhone(raw);
  if (!p) return esc(raw);
  return `<a href="tel:${p.tel}" class="num">${esc(p.text)}</a>${p.note ? ` <span class="muted">${esc(p.note)}</span>` : ""}`;
}
// Заглушки для неизвестных значений: «Нет открытых данных», «Цена по запросу» и т. п.
const unk = (kind = "none") => ({
  none: '<span class="unk">Нет открытых данных</span>',
  na: '<span class="unk">Не указано</span>',
  price: '<span class="unk req">Цена по запросу</span>',
  conf: '<span class="unk conf">Требует подтверждения</span>',
}[kind]);
// Бейджи кодов ОКВЭД и ОКПД2
function okvedTag(code, withName) {
  if (!code) return unk("none");
  const nm = App.data.okved[code] || "";
  return `<span class="code okved" title="${esc(nm)}"><b>ОКВЭД</b><span>${esc(code)}</span></span>${withName && nm ? ` <span class="muted">${esc(nm)}</span>` : ""}`;
}
function okpdTag(o, withName) {
  if (!o) return '<span class="unk">ОКПД2 не указан в источнике</span>';
  const inf = o.status === "INFERRED";
  return `<span class="code okpd2 ${inf ? "inf" : ""}" title="${esc(o.name)}${inf ? " — присвоено по классификатору, требует подтверждения" : o.status === "COMPANY" ? " — подтверждено предприятием" : ""}"><b>ОКПД2${inf ? " · присвоено" : ""}</b><span>${esc(o.code)}</span></span>${withName ? ` <span class="muted">${esc(o.name)}</span>` : ""}`;
}
// Кнопка «Источник», домен сайта, пометка пользовательских данных
const srcBtn = (id, label = "Источник") => id ? `<button class="srcbtn" data-src="${esc(id)}">${esc(label)}</button>` : "";
const domain = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return u; } };
const userTag = () => `<span class="st USER">Указано пользователем · не проверено</span>`;
// Вывод цены или заглушки, если цена не опубликована
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
    <dt>Предприятие</dt><dd><a href="#c.${esc(c.id)}" data-close>${esc(c.name)}</a></dd>
    <dt>URL</dt><dd><a href="${esc(s.source_url)}" target="_blank" rel="noopener">${esc(s.source_url)}</a></dd>
    <dt>Тип источника</dt><dd>${esc(sourceTypeTxt(s.source_type))} · приоритет ${esc(s.priority)} из 12</dd>
    <dt>Подтверждает</dt><dd>${s.confirms?.length ? esc(s.confirms.join(", ")) : '<span class="unk">Параметры не подтверждены — источник не прочитан</span>'}</dd>
    <dt>Дата публикации</dt><dd>${s.source_date ? fmtDate(s.source_date) : unk("na")}</dd>
    <dt>Проверено</dt><dd>${fmtDate(s.last_verified_at)}</dd>
    <dt>Результат обхода</dt><dd>${s.fetch_status === "OK" ? '<span class="v yes">Прочитан</span>' : `<span class="v no">${esc(fetchTxt(s.fetch_status))}</span>`}</dd>
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
// Закрытие панели по Esc и открытие источника по клику на [data-src]
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

/* ---- Риски и важные факты: правила по открытым данным базы (не заключение о благонадёжности) ---- */
const yearsSince = (d) => { if (!d) return null; const a = new Date(d), b = new Date(TODAY); let y = b.getFullYear() - a.getFullYear(); if (b < new Date(b.getFullYear(), a.getMonth(), a.getDate())) y--; return y; };
// Источник реквизитов: официальный ЕГРЮЛ, затем «Прозрачный бизнес», затем агрегатор
const egrulSrc = (c) => ["FNS_EGRUL", "FNS_PB", "EGRUL_AGGREGATOR"].map((t) => c.sources.find((s) => s.source_type === t)).find(Boolean);
// Статус юрлица: поле status_code из синхронизации с реестрами, для старых записей — по тексту legal_status
function legalState(c) {
  if (c.status_code) return c.status_code;
  const t = (c.legal_status || "").toLowerCase();
  if (!t) return null;
  if (t.includes("банкрот")) return "BANKRUPTCY";
  if (t.includes("стадии ликвидации")) return "LIQUIDATING";
  if (/ликвидир|прекращ/.test(t)) return "LIQUIDATED";
  if (t.includes("реорганиз")) return "REORGANIZING";
  return "ACTIVE";
}
const STATE_TXT = { ACTIVE: ["ok", "Действующее"], REORGANIZING: ["warn", "Реорганизация"], LIQUIDATING: ["bad", "Ликвидация"], BANKRUPTCY: ["bad", "Банкротство"], LIQUIDATED: ["bad", "Ликвидировано"] };
// Метка закрытия для карточек в списках: только для недействующих юрлиц
const stateTag = (c) => { const s = legalState(c); return s && s !== "ACTIVE" ? `<span class="egr-st ${STATE_TXT[s][0]}">${STATE_TXT[s][1]}</span>` : ""; };
// Суммы из отчётности ГИР БО приходят в тысячах рублей
function fmtRub(k) {
  if (k == null) return "—";
  const r = k * 1000, a = Math.abs(r), f = (x, d) => x.toFixed(d).replace(".", ",");
  return a >= 1e9 ? f(r / 1e9, 1) + " млрд ₽" : a >= 1e6 ? f(r / 1e6, 1) + " млн ₽" : a >= 1e3 ? f(r / 1e3, 0) + " тыс. ₽" : f(r, 0) + " ₽";
}
function companyRisks(c) {
  const risks = [], facts = [];
  const egr = egrulSrc(c)?.id, age = yearsSince(c.reg_date), st = legalState(c);
  const liquidated = st === "LIQUIDATED", bankrupt = st === "BANKRUPTCY";
  // Риски: high — критично, mid — требует внимания, low — к сведению
  if (bankrupt) risks.push({ level: "high", title: "Процедура банкротства", text: `${c.legal_status}. Исполнение договора под угрозой, сделки контролирует конкурсный управляющий.`, src: c.sources.find((s) => /банкрот/i.test((s.confirms || []).join(" ")))?.id || egr });
  if (liquidated) risks.push({ level: "high", title: "Юрлицо ликвидировано", text: `По сведениям ЕГРЮЛ: ${c.legal_status}. Заключать договор с этим лицом нельзя.`, src: egr });
  if (st === "LIQUIDATING") risks.push({ level: "high", title: "Юрлицо ликвидируется", text: `${c.legal_status}. Новые обязательства компания, скорее всего, исполнять не будет.`, src: egr });
  if (st === "REORGANIZING") risks.push({ level: "mid", title: "Реорганизация", text: "Права и обязательства перейдут к другому юрлицу. Уточните правопреемника до заключения договора.", src: egr });
  // Сигналы из реестров: недостоверность, долги, банкротные намерения, убытки и др. (см. sync/risks.py)
  for (const x of c.risk_signals || []) risks.push({ level: x.level, title: x.title, text: x.text, src: x.source_id });
  if (!c.inn) risks.push({ level: "high", title: "Реквизиты не подтверждены", text: "ИНН и ОГРН не найдены в открытых источниках. Сопоставить предприятие с ЕГРЮЛ нельзя.", src: c.sources[0]?.id });
  for (const d of c.discrepancies || []) {
    if (["Статус", "Реквизиты"].includes(d.field)) continue; // уже учтены выше
    risks.push({ level: "mid", title: `Расхождение: ${d.field.toLowerCase()}`, text: d.note, src: d.values[0]?.source_id });
  }
  for (const s of c.sources.filter((s) => s.source_type === "OFFICIAL_SITE" && s.fetch_status !== "OK"))
    risks.push({ level: "mid", title: "Официальный сайт не прочитан", text: `${domain(s.source_url)} недоступен для автоматической проверки. Данные с сайта нужно сверить вручную.`, src: s.id });
  if (age != null && age < 3 && !liquidated) risks.push({ level: "mid", title: "Молодая компания", text: `Зарегистрирована ${fmtDate(c.reg_date)}, на рынке меньше 3 лет.`, src: egr });
  if (!c.site && c.inn) risks.push({ level: "low", title: "Нет официального сайта", text: "Продукцию и контакты подтверждают только сторонние источники.", src: c.sources[0]?.id });
  if (!c.phones.length && !c.emails.length) risks.push({ level: "low", title: "Контакты не опубликованы", text: "Телефон и e-mail в открытых источниках не найдены.", src: null });
  // Важные факты
  if (age != null && !liquidated) facts.push({ title: `На рынке ${age} ${plural(age, "год", "года", "лет")}`, text: `Дата регистрации ${fmtDate(c.reg_date)}`, src: egr });
  if (st === "ACTIVE") facts.push({ title: "Действующее юрлицо", text: c.sync?.checked_at ? `Статус сверен с ЕГРЮЛ и Федресурсом ${fmtDate(c.sync.checked_at)}` : "Статус по сведениям ЕГРЮЛ", src: egr });
  // Показатели из реестров ФНС: отчётность, численность, налоги
  const reg = c.registry || {}, rs = reg.source_ids || {}, fin = reg.finance || [];
  if (fin[0]?.revenue != null) {
    const prev = fin[1]?.year === fin[0].year - 1 ? fin[1].revenue : null;
    const dyn = prev ? ` (${fin[0].revenue >= prev ? "+" : ""}${Math.round((fin[0].revenue / prev - 1) * 100)}% к ${fin[1].year})` : "";
    facts.push({ title: `Выручка ${fmtRub(fin[0].revenue)} за ${fin[0].year}`, text: `Бухгалтерская отчётность${dyn}` + (fin[0].net_profit > 0 ? `, чистая прибыль ${fmtRub(fin[0].net_profit)}` : ""), src: rs.girbo || rs.pb });
  }
  if (reg.headcount) facts.push({ title: `${reg.headcount} ${plural(reg.headcount, "сотрудник", "сотрудника", "сотрудников")}`, text: `Среднесписочная численность за ${reg.headcount_year || ""} год`, src: rs.opendata || rs.pb });
  if (reg.taxes_paid) facts.push({ title: `Уплачено налогов и взносов ${fmtRub(reg.taxes_paid / 1000)}`, text: `За ${reg.taxes_year || ""} год, режим ${reg.tax_mode || "не указан"}`, src: rs.opendata || rs.pb });
  if (reg.arrears === 0 && reg.arrears_date) facts.push({ title: "Нет задолженности по налогам", text: `По открытым данным ФНС на ${fmtDate(reg.arrears_date)}`, src: rs.opendata });
  if (reg.msp) facts.push({ title: `Реестр МСП: ${reg.msp}`, text: "Сведения ФНС", src: rs.pb });
  const siteOk = c.sources.find((s) => s.source_type === "OFFICIAL_SITE" && s.fetch_status === "OK");
  if (siteOk) facts.push({ title: "Официальный сайт подтверждён", text: `${domain(siteOk.source_url)} прочитан ${fmtDate(siteOk.last_verified_at)}`, src: siteOk.id });
  for (const x of c.certificates) facts.push({ title: "Сертификат или реестр", text: x.name, src: x.source_id });
  for (const x of c.capacities.filter((x) => !x.historical)) facts.push({ title: "Опубликована мощность", text: x.text, src: x.source_id });
  if (c.products.length) facts.push({ title: `${c.products.length} ${plural(c.products.length, "позиция", "позиции", "позиций")} продукции и услуг`, text: "Каждая позиция со ссылкой на источник", src: null });
  const order = { high: 0, mid: 1, low: 2 };
  risks.sort((a, b) => order[a.level] - order[b.level]);
  return { risks, facts, level: risks[0]?.level || "none" };
}
const RISK_TXT = { high: "Критично", mid: "Внимание", low: "К сведению", none: "Рисков не выявлено" };
// Короткий бейдж уровня риска для карточек в списках
function riskBadge(c) {
  const r = companyRisks(c);
  const n = r.risks.filter((x) => x.level !== "low").length;
  return `<span class="risk-badge ${r.level}">${r.level === "none" || !n ? "Рисков не выявлено" : `${RISK_TXT[r.level]}: ${n} ${plural(n, "риск", "риска", "рисков")}`}</span>`;
}
// Блок «Риски и важные факты» для карточки предприятия
function risksBlock(c) {
  const r = companyRisks(c);
  const ic = { high: "!", mid: "!", low: "i" };
  return `<section class="rf">
    <div class="rf-col"><h2 class="h2">Потенциальные риски <span class="rf-n ${r.level}">${r.risks.length}</span></h2>
      ${r.risks.length ? `<ul class="rf-list">${r.risks.map((x) => `<li class="${x.level}"><span class="rf-ic">${ic[x.level]}</span><div><b>${esc(x.title)}</b><span class="rf-lv">${RISK_TXT[x.level]}</span><p>${esc(x.text)} ${srcBtn(x.src)}</p></div></li>`).join("")}</ul>` : `<p class="rf-empty">По открытым данным базы рисков не выявлено.</p>`}
    </div>
    <div class="rf-col"><h2 class="h2">Важные факты <span class="rf-n ok">${r.facts.length}</span></h2>
      ${r.facts.length ? `<ul class="rf-list">${r.facts.map((x) => `<li class="ok"><span class="rf-ic">✓</span><div><b>${esc(x.title)}</b><p>${esc(x.text)} ${srcBtn(x.src)}</p></div></li>`).join("")}</ul>` : `<p class="rf-empty">Подтверждённых фактов пока нет.</p>`}
    </div>
    <p class="rf-note">Риски и факты определяются автоматически по реестрам ФНС (ЕГРЮЛ, «Прозрачный бизнес», открытые данные, ГИР БО), Федресурсу и данным базы${c.sync?.checked_at ? `, последняя сверка ${fmtDate(c.sync.checked_at)}` : ""}. Это не заключение о благонадёжности. ${c.sync?.sources?.checko === "OK" ? "Арбитражные дела и исполнительные производства загружены из Checko." : "Арбитражные дела и исполнительные производства в базу не загружены: перед сделкой проверьте их в картотеке арбитражных дел и банке данных ФССП."}</p>
  </section>`;
}

/* ---- Карточка реквизитов юрлица (формат выписки ЕГРЮЛ) ---- */
function requisitesCard(c) {
  const egr = egrulSrc(c);
  const s = legalState(c), st = s ? STATE_TXT[s] : ["none", "Статус не подтверждён"];
  const type = !c.ogrn ? null : c.ogrn.length === 15 ? "Индивидуальный предприниматель" : "Юридическое лицо";
  const age = yearsSince(c.reg_date);
  const v = (x, cls = "num") => x ? `<span class="${cls}">${esc(x)}</span>` : unk("none");
  return `<section class="egr">
    <header><h2>${esc(c.legal_name || c.name)}</h2><span class="egr-st ${st[0]}">${st[1]}</span></header>
    <div class="egr-grid">
      <div><dt>ОГРН</dt><dd>${v(c.ogrn)}</dd></div>
      <div class="egr-ids"><div><dt>ИНН</dt><dd>${v(c.inn)}</dd></div><div><dt>КПП</dt><dd>${v(c.kpp)}</dd></div><div><dt>ОКПО</dt><dd>${v(c.okpo)}</dd></div></div>
      <div><dt>Дата регистрации</dt><dd>${c.reg_date ? `${fmtDate(c.reg_date)}${age != null ? ` <span class="muted">· ${age} ${plural(age, "год", "года", "лет")}</span>` : ""}` : unk("none")}</dd></div>
      <div><dt>Тип организации</dt><dd>${type ? esc(type) : unk("none")}</dd></div>
      <div class="wide"><dt>Основной вид деятельности</dt><dd>${c.okved_main ? `<span class="num">${esc(c.okved_main)}</span> ${esc(App.data.okved[c.okved_main] || "")}` : unk("none")}</dd></div>
      <div class="wide"><dt>Юридический адрес</dt><dd>${c.address ? esc(c.address) : unk("none")}</dd></div>
    </div>
    <footer>${egr ? `<span class="egr-ok">✓</span> ${c.sync?.checked_at ? "Сверено с реестрами" : "Актуально на"} ${fmtDate(c.sync?.checked_at || egr.last_verified_at)} ${srcBtn(egr.id, "Источник: сведения ЕГРЮЛ")}` : `<span class="muted">Сведения ЕГРЮЛ по предприятию не найдены</span>`}</footer>
  </section>`;
}

/* ---- Проверка реквизитов по контрольным суммам (алгоритмы ФНС и Росстата) ---- */
const _digits = (s) => s.split("").map(Number);
function innOk(s) {
  if (!/^\d{10}$|^\d{12}$/.test(s)) return false;
  const n = _digits(s), cs = (w) => w.reduce((a, x, i) => a + x * n[i], 0) % 11 % 10;
  if (s.length === 10) return cs([2, 4, 10, 3, 5, 9, 4, 6, 8]) === n[9];
  return cs([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) === n[10] && cs([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) === n[11];
}
function ogrnOk(s) {
  if (/^\d{13}$/.test(s)) return Number(BigInt(s.slice(0, 12)) % 11n % 10n) === +s[12];
  if (/^\d{15}$/.test(s)) return Number(BigInt(s.slice(0, 14)) % 13n % 10n) === +s[14];
  return false;
}
const kppOk = (s) => /^\d{4}[\dA-Z]{2}\d{3}$/.test(s);
function okpoOk(s) {
  if (!/^\d{8}$|^\d{10}$/.test(s)) return false;
  const n = _digits(s), body = n.slice(0, -1);
  const sum = (shift) => body.reduce((a, x, i) => a + x * (((i + shift) % 10) + 1), 0) % 11;
  let c = sum(0); if (c === 10) { c = sum(2); if (c === 10) c = 0; }
  return c === n[n.length - 1];
}
