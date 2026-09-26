// Сквозная проверка сайта в настоящем браузере (Chrome или Edge без окна, через DevTools Protocol) против сервера на PostgreSQL.
// Проверяет: перенос данных из localStorage на сервер, размер загрузки каталога, догрузку полной карточки, видимость заявок
// и откликов между пользователями, запрет чужих правок, вход модератора и решение по регистрации.
//
//   node tools/e2e_site.mjs                      # сервер http://127.0.0.1:8765 (start-local.cmd)
//   PK_E2E_URL=http://127.0.0.1:8000 PK_E2E_BROWSER="/usr/bin/google-chrome" node tools/e2e_site.mjs
//
// Модератор входит токеном dev-admin: так работает только локальный сервер без PK_TOKENS (или задайте PK_E2E_ADMIN_TOKEN).
// Тест создаёт записи в базах сервера — запускайте его на локальной или тестовой установке, не на рабочей.
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BASE = process.env.PK_E2E_URL || "http://127.0.0.1:8765";
const CHROME = process.env.PK_E2E_BROWSER || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const ADMIN = process.env.PK_E2E_ADMIN_TOKEN || "dev-admin";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ok = 0, fail = 0;
const check = (name, cond, info = "") => { if (cond) { ok++; console.log("  ✓", name, info); } else { fail++; console.log("  ✗", name, info); } };

async function browser(port) {
  const dir = mkdtempSync(join(tmpdir(), "e2e-"));
  const p = spawn(CHROME, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${dir}`, "--no-first-run", "--disable-gpu", "about:blank"], { stdio: "ignore" });
  for (let i = 0; i < 50; i++) { try { await fetch(`http://127.0.0.1:${port}/json/version`); break; } catch (e) { await sleep(200); } }
  const t = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json();
  const ws = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r));
  let id = 0; const pending = new Map();
  ws.addEventListener("message", (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } });
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }); if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails).slice(0, 400)); return r.result?.result?.value; };
  const go = async (url) => { await send("Page.navigate", { url }); await sleep(300); for (let i = 0; i < 100; i++) { if (await ev("typeof App !== \"undefined\" && !!App.data && App.profileLoaded").catch(() => false)) return; await sleep(200); } throw new Error("page did not load"); };
  await send("Page.enable"); await send("Runtime.enable"); await send("Page.bringToFront"); await send("Emulation.setFocusEmulationEnabled", { enabled: true });
  return { ev, go, close: () => { ws.close(); p.kill(); } };
}

const RUN = Date.now().toString(36);
const A = await browser(9333);
console.log("1. Старые данные из localStorage переносятся на сервер");
await A.go(BASE + "/");
await A.ev(`(() => { localStorage.clear();
  const s = (k, v) => localStorage.setItem("pk:" + k, JSON.stringify(v));
  s("offers", [{ id: "o-legacy-${RUN}", title: "Прокат из браузера", kind_label: "Материалы", company_name: "ООО Тест", author: "local", status: "NEW", created_at: "2026-09-20T10:00:00.000Z" }]);
  s("requests", [{ id: "r-legacy-${RUN}", what: "Заготовка из браузера", author: "local", status: "NEW", created_at: "2026-09-20T10:00:00.000Z" }]);
  s("registrations", [{ id: "local", account: { fio: "Браузерный Пользователь", position: "Снабжение", email: "b@example.ru", phone: "" }, company: { name: "ООО Браузер", inn: "3435000717" }, status: "PENDING", submitted_at: "2026-09-20T10:00:00.000Z", edit: false }]);
  s("profile", { city: "Камышин", favorites: ["c:ko"], compare: [], saved: [], companies: [], warehouses: [], account: { fio: "Браузерный Пользователь", position: "Снабжение", email: "b@example.ru" }, company: { name: "ООО Браузер", status: "На проверке у модератора", submitted_at: "2026-09-20T10:00:00.000Z" } });
  s("chains", [{ id: "chain-legacy-${RUN}", title: "Цепочка из браузера", nodes: [], edges: [], kind: "chain" }]);
  return true; })()`);
await A.go(BASE + "/?r=" + Date.now());
await sleep(1500);
const st = await A.ev(`({ mode: App.mode, uid: App.uid, offers: App.offers.map(x => x.id), requests: App.requests.map(x => x.id), city: App.profile.city,
  chains: App.chains.map(c => c.id), imported: JSON.parse(localStorage.getItem("pk:imported") || "null"), companies: App.data.companies.length })`);
check("режим сервера", st.mode === "api", st.mode);
check("каталог загружен с сервера", st.companies > 4000, st.companies + " предприятий");
check("предложение из браузера на сервере", st.offers.includes(`o-legacy-${RUN}`));
check("заявка из браузера на сервере", st.requests.includes(`r-legacy-${RUN}`));
check("профиль и цепочка перенесены", st.city === "Камышин" && st.chains.includes(`chain-legacy-${RUN}`));
check("отметка о переносе", !!st.imported?.result, JSON.stringify(st.imported?.result));

console.log("2. Размер загрузки каталога");
const net = await A.ev(`(() => { const e = performance.getEntriesByType("resource").find(x => x.name.includes("/api/v1/bundle")); return e && { transfer: e.transferSize, encoded: e.encodedBodySize, decoded: e.decodedBodySize }; })()`);
check("каталог сжат", net && net.encoded < 1_000_000, JSON.stringify(net));
await A.go(BASE + "/?again=" + Date.now());
const net2 = await A.ev(`(() => { const e = performance.getEntriesByType("resource").find(x => x.name.includes("/api/v1/bundle")); return e && { transfer: e.transferSize, status: e.responseStatus }; })()`);
check("повторный заход без скачивания каталога (304)", net2 && (net2.status === 304 || net2.transfer < 2000), JSON.stringify(net2));

console.log("3. Каталог и карточка предприятия");
await A.ev(`location.hash = "#companies"`); await sleep(800);
const list = await A.ev(`({ h1: document.querySelector(".h1")?.textContent, cards: document.querySelectorAll("#app a[href^='#c.']").length })`);
check("каталог отрисован", list.h1 === "Каталог предприятий" && list.cards > 5, JSON.stringify(list));
await A.ev(`location.hash = "#c.ko"`); await sleep(1500);
const card = await A.ev(`({ light: !!App.C.ko._light, loading: document.getElementById("app").textContent.includes("Загружаем полные сведения"), src: App.C.ko.sources[0]?.source_title, risks: document.querySelectorAll(".rf-list li").length })`);
check("полная карточка догружена", !card.light && !card.loading && !!card.src, JSON.stringify(card));

console.log("4. Заявка от пользователя A видна пользователю B и модератору");
const created = await A.ev(`Store.put("requests", "r-e2e-" + Date.now().toString(36), { what: "Нужны подшипники, 100 шт", qty: "100", unit: "шт", region: "34", city: "Волгоград", author: App.uid, status: "NEW", created_at: nowIso(), company_id: null })`);
check("заявка сохранена на сервере", created === true);
const reqId = await A.ev(`App.requests.find(r => r.what === "Нужны подшипники, 100 шт")?.id`);
const B = await browser(9334);
await B.go(BASE + "/");
const bSees = await B.ev(`({ uid: App.uid, sees: App.requests.some(r => r.id === ${JSON.stringify(reqId)}), regs: App.registrations.length })`);
check("пользователь B видит заявку A", bSees.sees);
check("пользователь B не видит чужие регистрации", bSees.regs === 0);
const resp = await B.ev(`Store.put("responses", "resp-e2e-" + Date.now().toString(36), { request_id: ${JSON.stringify(reqId)}, company: "ООО Подшипник", text: "Есть в наличии", price: "", author: App.uid, at: nowIso() })`);
check("отклик B сохранён", resp === true);
const forge = await B.ev(`fetch("/api/v1/store/requests/${reqId}", { method: "PUT", headers: { "Content-Type": "application/json", Authorization: "Bearer " + JSON.parse(localStorage.getItem("pk:session")) }, body: JSON.stringify({ what: "подмена" }) }).then(r => r.status)`);
check("B не может изменить заявку A", forge === 403, forge);
await A.ev(`Store.refresh()`); await sleep(300);
check("A видит отклик B", await A.ev(`App.responses.some(x => x.request_id === ${JSON.stringify(reqId)})`));

console.log("5. Модератор");
await B.ev(`localStorage.setItem("pk:apitoken", JSON.stringify(${JSON.stringify(ADMIN)})); Store.init()`); await sleep(1200);
const mod = await B.ev(`({ canEdit: App.canEdit, regs: App.registrations.map(r => r.company?.name) })`);
check("вход по токену модератора", mod.canEdit === true);
check("модератор видит регистрацию из браузера A", mod.regs.includes("ООО Браузер"), JSON.stringify(mod.regs));
const aUid = await A.ev(`App.uid`);
await B.ev(`location.hash = "#admin.moderation"`); await sleep(600);
await B.ev(`moderateRegistration(${JSON.stringify(aUid)}, "APPROVED", "")`); await sleep(500);
await A.ev(`Store.refresh()`); await sleep(500);
const dec = await A.ev(`({ mod: App.moderation.find(m => m.id === App.uid)?.status })`);
check("пользователь A видит решение модератора", dec.mod === "APPROVED", JSON.stringify(dec));

A.close(); B.close();
console.log(`\nИтог: ${ok} проверок пройдено, ${fail} не пройдено`);
process.exit(fail ? 1 : 0);
