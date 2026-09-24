/* ===== Личный кабинет и административная панель ===== */

/* ---------- Личный кабинет: предложения, заявки, предприятия, склады, настройки ---------- */
ROUTES.cabinet = (arg) => {
  // Без регистрации кабинет недоступен: показываем мастер регистрации
  if (!App.profile.account || UI.reg) return regView();
  if (arg) UI.cabinetTab = arg;
  const t = UI.cabinetTab;
  const unread = (App.profile.inbox || []).filter((x) => !x.read).length;
  const tabs = [["company", "Компания"], ["inbox", "Уведомления" + (unread ? ` <span class=\"tab-n\">${unread}</span>` : "")], ["offers", "Мои предложения"], ["requests", "Мои заявки"], ["companies", "Мои предприятия"], ["warehouses", "Мои склады"], ["favorites", "Избранное"], ["saved", "Сохранённые поиски"], ["messages", "Сообщения"], ["settings", "Настройки"]];
  const myOffers = App.offers.filter((o) => o.author === App.uid), myReq = App.requests.filter((r) => r.author === App.uid);
  const co = App.profile.company || {}, acc = App.profile.account;
  let body = "";
  if (t === "company") body = `<div class="sec-h"><h2 class="h2">Данные компании</h2><button class="btn" data-act="reg-edit">Изменить данные</button></div>
    <div class="co-top">
      <section class="egr"><header><h2>${esc(co.legal_name || co.name)}</h2><span class="egr-st ${co.status === "Подтверждено" ? "ok" : "none"}">${esc(co.status || "На проверке у модератора")}</span></header>
        <div class="egr-grid">
          <div><dt>ОГРН</dt><dd class="num">${esc(co.ogrn || "")}</dd></div>
          <div class="egr-ids"><div><dt>ИНН</dt><dd class="num">${esc(co.inn || "")}</dd></div><div><dt>КПП</dt><dd class="num">${co.kpp ? esc(co.kpp) : unk("none")}</dd></div><div><dt>ОКПО</dt><dd class="num">${co.okpo ? esc(co.okpo) : unk("none")}</dd></div></div>
          <div><dt>Основной ОКВЭД</dt><dd>${esc(co.okved_main || "")} ${esc(App.data.okved[co.okved_main] || "")}</dd></div>
          <div><dt>Дата регистрации</dt><dd>${co.reg_date ? esc(co.reg_date) : unk("none")}</dd></div>
          <div class="wide"><dt>Юридический адрес</dt><dd>${esc(co.address || "")}</dd></div>
          ${co.postal_address ? `<div class="wide"><dt>Почтовый адрес</dt><dd>${esc(co.postal_address)}</dd></div>` : ""}
        </div>
        <footer>${co.base_id ? `Связана с карточкой <a href="#c.${esc(co.base_id)}">${esc(App.C[co.base_id]?.name || "")}</a>` : "Компании пока нет в проверенной базе: карточка появится после проверки модератором."}</footer>
      </section>
      <section class="card"><h2 class="h2" style="margin-bottom:12px">Представитель</h2>
        <dl class="kv"><dt>ФИО</dt><dd>${esc(acc.fio)}</dd><dt>Должность</dt><dd>${esc(acc.position)}</dd><dt>E-mail</dt><dd>${esc(acc.email)}</dd><dt>Телефон</dt><dd>${acc.phone ? esc(acc.phone) : unk("none")}</dd><dt>Регистрация</dt><dd>${fmtDate(acc.registered_at)}</dd>
        <dt>Контакты компании</dt><dd>${[co.site, co.phone, co.email].filter(Boolean).map(esc).join("<br>") || unk("none")}</dd></dl></section>
    </div>
    <div class="note" style="margin-top:16px">Модератор регионального отделения сверит данные с выпиской ЕГРЮЛ и подтвердит ваши права. До подтверждения предложения от имени компании помечаются как «указано пользователем».</div>`;
  if (t === "inbox") body = inboxView();
  if (t === "offers") body = `<div class="sec-h"><h2 class="h2">Мои предложения (${myOffers.length})</h2><button class="btn pri" data-act="offer-new">Разместить предложение</button></div>${myOffers.map(offerRow).join("") || '<div class="note">Вы ещё не размещали предложений.</div>'}`;
  if (t === "requests") body = `<div class="sec-h"><h2 class="h2">Мои заявки (${myReq.length})</h2><button class="btn pri" data-act="request-new">Создать заявку</button></div>${myReq.map(requestRow).join("") || '<div class="note">Вы ещё не создавали заявок.</div>'}`;
  if (t === "companies") body = `<div class="sec-h"><h2 class="h2">Мои предприятия</h2></div>
    <p class="muted">Привяжите предприятие к аккаунту, чтобы размещать предложения от его имени и подтверждать данные. Права подтверждаются модератором по документам.</p>
    ${App.profile.companies.length ? `<ul class="list">${App.profile.companies.map((x) => `<li><span><a href="#c.${esc(x.company_id)}">${esc(App.C[x.company_id]?.name)}</a><br><span class="muted">${esc(x.role)} · ${esc(x.status)}</span></span><button class="btn sm txt" data-act="unclaim" data-id="${esc(x.company_id)}">Отвязать</button></li>`).join("")}</ul>` : '<div class="note">Предприятий нет.</div>'}
    <form id="claim-form" class="form" style="margin-top:16px"><div class="field"><label for="cl-co">Предприятие</label><select class="sel" id="cl-co" name="company_id">${App.data.companies.map((c) => `<option value="${esc(c.id)}">${esc(c.name)}</option>`).join("")}</select></div>
    <div class="field"><label for="cl-role">Ваша роль</label><input class="inp" id="cl-role" name="role" required placeholder="например: отдел снабжения"></div>
    <div class="field" style="justify-content:flex-end"><button class="btn pri" type="submit">Отправить запрос на привязку</button></div></form>`;
  if (t === "warehouses") body = `<div class="sec-h"><h2 class="h2">Мои склады и площадки</h2></div>
    <p class="muted">Площадки и склады — отдельные сущности. Остатки указываются только вами и помечаются как «указано пользователем».</p>
    ${App.profile.warehouses.length ? `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Название</th><th>Тип</th><th>Адрес</th><th>Город</th><th>Складской объём</th><th>Доступный объём</th><th></th></tr></thead><tbody>${App.profile.warehouses.map((w) => `<tr><td>${esc(w.name)}</td><td>${esc(w.type)}</td><td>${esc(w.address)}</td><td>${esc(w.city)}</td><td>${w.capacity ? esc(w.capacity) : unk("na")}</td><td>${w.available ? esc(w.available) : unk("na")}</td><td><button class="btn sm txt" data-act="wh-del" data-id="${esc(w.id)}">Удалить</button></td></tr>`).join("")}</tbody></table></div>` : '<div class="note">Складов нет.</div>'}
    <form id="wh-form" class="form" style="margin-top:16px">
      <div class="field"><label for="wh-name">Название *</label><input class="inp" id="wh-name" name="name" required></div>
      <div class="field"><label for="wh-type">Тип</label><select class="sel" id="wh-type" name="type"><option>Склад</option><option>Завод</option><option>Цех</option><option>Производственная площадка</option><option>Филиал</option></select></div>
      <div class="field"><label for="wh-addr">Адрес</label><input class="inp" id="wh-addr" name="address"></div>
      <div class="field"><label for="wh-city">Город</label><select class="sel" id="wh-city" name="city">${Object.keys(App.data.cities).map((c) => `<option>${c}</option>`).join("")}</select></div>
      <div class="field"><label for="wh-cap">Складской объём</label><input class="inp" id="wh-cap" name="capacity" placeholder="например 2000 м²"></div>
      <div class="field"><label for="wh-av">Доступный объём</label><input class="inp" id="wh-av" name="available"></div>
      <div class="field full"><button class="btn pri" type="submit">Добавить</button></div></form>`;
  if (t === "favorites") {
    const fav = App.profile.favorites.map((k) => { const [tp, id] = k.split(":"); return tp === "c" ? App.C[id] && `<li><span><a href="#c.${esc(id)}">${esc(App.C[id].name)}</a></span><button class="btn sm txt" data-fav="${k}">Убрать</button></li>` : App.P[id] && `<li><span><a href="#p.${esc(id)}">${esc(App.P[id].name)}</a></span><button class="btn sm txt" data-fav="${k}">Убрать</button></li>`; }).filter(Boolean);
    body = `<h2 class="h2" style="margin-bottom:12px">Избранное</h2>${fav.length ? `<ul class="list">${fav.join("")}</ul>` : '<div class="note">Сохраняйте предприятия кнопкой «В избранное».</div>'}`;
  }
  if (t === "saved") body = `<h2 class="h2" style="margin-bottom:12px">Сохранённые поиски</h2>${App.profile.saved.length ? `<ul class="list">${App.profile.saved.map((s, i) => `<li><span>${esc(s.text)}<br><span class="muted">${fmtDate(s.at)}</span></span><span class="row"><button class="btn sm" data-act="saved-run" data-i="${i}">Повторить</button><button class="btn sm txt" data-act="saved-del" data-i="${i}">Удалить</button></span></li>`).join("")}</ul>` : '<div class="note">Сохраните поиск на странице «Поиск поставщика».</div>'}`;
  if (t === "messages") {
    const inbox = myReq.flatMap((r) => responsesOf(r).map((x) => ({ ...x, r })));
    const sent = App.requests.flatMap((r) => responsesOf(r).filter((x) => x.author === App.uid).map((x) => ({ ...x, r })));
    body = `<h2 class="h2" style="margin-bottom:12px">Сообщения</h2>
      <div class="grid2"><div><div class="label" style="margin-bottom:8px">Отклики на мои заявки (${inbox.length})</div>${inbox.map((m) => `<div class="card flat" style="margin-bottom:8px"><b>${esc(m.company)}</b> → <a href="#r.${esc(m.r.id)}">${esc(m.r.what)}</a><div class="muted">${fmtDate(m.at)}</div><div>${esc(m.text)}</div></div>`).join("") || '<div class="note">Откликов нет.</div>'}</div>
      <div><div class="label" style="margin-bottom:8px">Мои отклики (${sent.length})</div>${sent.map((m) => `<div class="card flat" style="margin-bottom:8px"><a href="#r.${esc(m.r.id)}">${esc(m.r.what)}</a><div class="muted">${fmtDate(m.at)}</div><div>${esc(m.text)}</div></div>`).join("") || '<div class="note">Вы не откликались на заявки.</div>'}</div></div>`;
  }
  if (t === "settings") body = `<h2 class="h2" style="margin-bottom:12px">Настройки</h2>
    <form id="settings-form" class="form"><div class="field"><label for="st-city">Город вашего предприятия (для расчёта расстояний)</label><select class="sel" id="st-city" name="city">${Object.keys(App.data.cities).map((c) => `<option ${App.profile.city === c ? "selected" : ""}>${c}</option>`).join("")}</select></div>
    <div class="field" style="justify-content:flex-end"><button class="btn pri" type="submit" style="align-self:flex-start">Сохранить</button></div></form>
    <section class="sec" id="notify-settings"><h2 class="h2" style="margin-bottom:12px">Уведомления в мессенджерах</h2>
      <p class="muted" style="margin:0 0 16px;max-width:760px">На сайте уведомления приходят всегда, во вкладку «Уведомления». Здесь можно дублировать их в Telegram и ВКонтакте.</p>
      ${notifyPanel()}</section>`;
  return `<div class="wrap page">${crumbs(["#cabinet", "Личный кабинет"])}
  <div class="sec-h"><div><h1 class="h1">Личный кабинет</h1><p class="muted" style="margin:4px 0 0">${esc(acc.fio)} · ${esc(co.name || "")} · <span class="cab-st">${esc(co.status || "На проверке у модератора")}</span></p></div><div class="row"><a class="btn" href="#chains">Мои цепочки (${App.chains.length})</a><a class="btn" href="#compare">Сравнение (${App.profile.compare.length})</a></div></div>
  <div class="tabs" role="tablist">${tabs.map(([k, n]) => `<button role="tab" aria-selected="${t === k}" data-ctab="${k}">${n}</button>`).join("")}</div>${body}</div>`;
};

/* ---------- Регистрация представителя компании: 3 шага ---------- */
// Поля карточки компании: [ключ, подпись, обязательное, подсказка]
const REG_CO_FIELDS = [
  ["name", "Краткое наименование", true, "Например: ОАО «Волгограднефтемаш»"],
  ["legal_name", "Полное наименование", true, "Как в выписке ЕГРЮЛ"],
  ["inn", "ИНН", true, "10 цифр для организации, 12 для ИП"],
  ["ogrn", "ОГРН или ОГРНИП", true, "13 цифр для организации, 15 для ИП"],
  ["kpp", "КПП", false, "9 знаков, обязателен для организаций"],
  ["okpo", "ОКПО", false, "8 цифр для организации, 10 для ИП"],
  ["okved_main", "Основной ОКВЭД", true, "Например: 28.99.9"],
  ["reg_date", "Дата регистрации", false, "ДД.ММ.ГГГГ"],
  ["address", "Юридический адрес", true, ""],
  ["postal_address", "Почтовый адрес", false, "Если отличается от юридического"],
  ["site", "Сайт", false, ""],
  ["phone", "Телефон компании", false, ""],
  ["email", "E-mail компании", false, ""],
];
const REG_ACC_FIELDS = [
  ["fio", "ФИО", true, "Иванов Иван Иванович"],
  ["position", "Должность", true, "Например: начальник отдела снабжения"],
  ["email", "Рабочий e-mail", true, "На него придёт подтверждение"],
  ["phone", "Телефон", true, "+7 …"],
];
const newReg = () => ({ step: 1, acc: {}, co: {}, from: null, fromKeys: [], checked: false, consent: false, errors: {}, edit: false });

// Проверка шага: возвращает объект ошибок по полям
function regValidate(step) {
  const r = UI.reg, e = {};
  if (step === 1) {
    for (const [k, , req] of REG_ACC_FIELDS) if (req && !(r.acc[k] || "").trim()) e["acc." + k] = "Заполните поле";
    if (r.acc.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(r.acc.email.trim())) e["acc.email"] = "Проверьте адрес e-mail";
    if (!r.consent) e.consent = "Нужно согласие на обработку персональных данных";
  }
  if (step === 2) {
    const co = r.co, v = (k) => (co[k] || "").trim();
    for (const [k, , req] of REG_CO_FIELDS) if (req && !v(k)) e["co." + k] = "Заполните поле";
    if (v("inn") && !innOk(v("inn"))) e["co.inn"] = "ИНН не проходит проверку контрольной суммы";
    if (v("ogrn") && !ogrnOk(v("ogrn"))) e["co.ogrn"] = "ОГРН не проходит проверку контрольной суммы";
    if (v("inn").length === 10 && !v("kpp")) e["co.kpp"] = "Для организации укажите КПП";
    if (v("kpp") && !kppOk(v("kpp").toUpperCase())) e["co.kpp"] = "КПП: 9 знаков, например 344601001";
    if (v("okpo") && !okpoOk(v("okpo"))) e["co.okpo"] = "ОКПО не проходит проверку контрольной суммы";
    if (v("inn") && v("ogrn") && (v("inn").length === 12) !== (v("ogrn").length === 15)) e["co.ogrn"] = "ИНН и ОГРН относятся к разным типам лиц (организация или ИП)";
    if (!r.checked) e.checked = "Подтвердите, что проверили данные";
  }
  return e;
}

// Подсказки по названию или ИНН: предприятия из базы и участники регионального отделения
const _normName = (s) => String(s || "").toLowerCase().replace(/ё/g, "е").replace(/[«»"'().,]/g, " ").replace(/\b(ооо|оао|зао|пао|ао|ип|нпо|пк|фнпц|ано)\b/g, " ").replace(/\s+/g, " ").trim();
function regSuggest(q) {
  const s = _normName(q); if (s.length < 2) return [];
  const toks = s.split(" ");
  const hit = (hay) => toks.every((t) => hay.includes(t));
  const base = App.data.companies.filter((c) => hit(_normName([c.name, c.short, c.legal_name].join(" "))) || (c.inn && c.inn.startsWith(q.trim())))
    .map((c) => ({ kind: "base", id: c.id, title: c.name, sub: [c.inn ? "ИНН " + c.inn : "ИНН не найден", c.city, STATUS_TXT[c.verification_status]].filter(Boolean).join(" · ") }));
  const ro = RO_MEMBERS.orgs.filter(([n, id]) => !(id && App.C[id]) && hit(_normName(n)))
    .map(([n]) => ({ kind: "ro", title: n, sub: "Участник регионального отделения · реквизитов в базе пока нет" }));
  return [...base, ...ro].slice(0, 8);
}
function regSuggestHtml(list) {
  if (!list.length) return "";
  return list.map((x) => `<li><button type="button" ${x.kind === "base" ? `data-reg-pick="${esc(x.id)}"` : `data-reg-pick-name="${esc(x.title)}"`}><b>${esc(x.title)}</b><span>${esc(x.sub)}</span></button></li>`).join("");
}
// Выбор компании из подсказки: подгружаем известные реквизиты
function regPick(id, name) {
  const r = UI.reg;
  if (id) {
    const c = App.C[id];
    const map = { name: c.name, legal_name: c.legal_name, inn: c.inn, ogrn: c.ogrn, kpp: c.kpp, okpo: c.okpo, okved_main: c.okved_main,
      reg_date: c.reg_date ? fmtDate(c.reg_date) : "", address: c.address, site: c.site, phone: c.phones[0], email: c.emails[0] };
    r.co = {}; r.fromKeys = [];
    for (const [k, v] of Object.entries(map)) if (v) { r.co[k] = v; r.fromKeys.push(k); }
    r.from = { id, name: c.name, egr: egrulSrc(c) };
  } else { r.co = { name }; r.fromKeys = []; r.from = { id: null, name }; }
  r.checked = false; r.errors = {};
  render();
}

function regField(scope, [k, label, req, hint]) {
  const r = UI.reg, val = r[scope][k] || "", err = r.errors[scope + "." + k];
  const fromBase = scope === "co" && r.fromKeys.includes(k);
  const tag = fromBase ? `<span class="rg-tag base">из базы</span>` : scope === "co" && r.from && !val ? `<span class="rg-tag fill">${req ? "заполните" : "нет в базе"}</span>` : "";
  const wide = ["name", "legal_name", "address", "postal_address"].includes(k) ? " full" : "";
  return `<div class="field${wide}${err ? " has-err" : ""}"><label for="rg-${scope}-${k}">${label}${req ? " *" : ""} ${tag}</label>
    <input class="inp${fromBase ? " from-base" : ""}" id="rg-${scope}-${k}" data-rf="${scope}.${k}" value="${esc(val)}" ${hint ? `placeholder="${esc(hint)}"` : ""} ${req ? "required" : ""} ${["inn", "ogrn", "okpo"].includes(k) ? 'inputmode="numeric"' : ""} autocomplete="off">
    ${err ? `<span class="rg-err">${esc(err)}</span>` : ""}</div>`;
}

function regView() {
  const r = UI.reg || (UI.reg = newReg());
  const steps = ["Представитель", "Компания", "Уведомления"];
  const bar = `<ol class="rg-steps">${steps.map((s, i) => `<li class="${i + 1 === r.step ? "on" : i + 1 < r.step ? "done" : ""}"><span>${i + 1 < r.step ? "✓" : i + 1}</span>${s}</li>`).join("")}</ol>`;
  let body = "";
  if (r.step === 1) body = `<form id="reg-form" class="rg-card" novalidate>
      <h2 class="h2">Данные представителя</h2>
      <p class="muted">Регистрируйтесь от имени компании, которую представляете. Права подтвердит модератор регионального отделения.</p>
      <div class="form">${REG_ACC_FIELDS.map((f) => regField("acc", f)).join("")}</div>
      <label class="chk rg-consent${r.errors.consent ? " has-err" : ""}"><input type="checkbox" data-rchk="consent" ${r.consent ? "checked" : ""}> Согласен на обработку персональных данных в соответствии с 152-ФЗ</label>
      ${r.errors.consent ? `<span class="rg-err">${esc(r.errors.consent)}</span>` : ""}
      <div class="rg-nav"><span></span><button class="btn pri" type="submit">Далее: компания</button></div>
    </form>`;
  if (r.step === 2) body = `<form id="reg-form" class="rg-card" novalidate>
      <h2 class="h2">Данные компании</h2>
      <p class="muted">Начните вводить название или ИНН. Если компания уже есть в базе, мы подставим известные реквизиты.</p>
      <div class="rg-find">
        <label class="sr" for="rg-find">Название или ИНН компании</label>
        <input class="inp" id="rg-find" data-rq="1" placeholder="Название или ИНН, например «Метеор» или 3435000717" autocomplete="off" value="">
        <ul class="rg-sugg" id="rg-sugg"></ul>
      </div>
      ${r.from ? `<div class="rg-loaded"><div><b>${r.from.id ? "Реквизиты подгружены из базы" : "Компания выбрана из списка участников отделения"}:</b> ${esc(r.from.name)}
        ${r.from.egr ? `<span class="muted">· источник: сведения ЕГРЮЛ, актуально на ${fmtDate(r.from.egr.last_verified_at)}</span>` : r.from.id ? "" : `<span class="muted">· реквизитов в базе нет, заполните вручную</span>`}</div>
        <button type="button" class="btn sm txt" data-act="reg-clear">Очистить</button></div>` : ""}
      <div class="form">${REG_CO_FIELDS.map((f) => regField("co", f)).join("")}</div>
      <div class="rg-warn${r.errors.checked ? " has-err" : ""}">
        <b>Проверьте все данные вручную</b>
        <p>Реквизиты подставлены из открытых источников и могли устареть. Сверьте каждое поле с выпиской ЕГРЮЛ и учредительными документами, исправьте ошибки и заполните пустые поля. Регистрация продолжится только после вашего подтверждения.</p>
        <label class="chk"><input type="checkbox" data-rchk="checked" ${r.checked ? "checked" : ""}> Я проверил все данные компании, они верны, и я уполномочен представлять эту компанию</label>
        ${r.errors.checked ? `<span class="rg-err">${esc(r.errors.checked)}</span>` : ""}
      </div>
      <div class="rg-nav">${r.edit ? `<button class="btn" type="button" data-act="reg-cancel">Отмена</button>` : `<button class="btn" type="button" data-act="reg-back">Назад</button>`}<button class="btn pri" type="submit">${r.edit ? "Сохранить изменения" : "Далее: уведомления"}</button></div>
    </form>`;
  if (r.step === 3) body = `<div class="rg-card">
      <h2 class="h2">Уведомления</h2>
      <p class="muted">Выберите, куда присылать новости о заявках, откликах и проверке компании. Настройки можно изменить в любой момент во вкладке «Уведомления».</p>
      ${notifyPanel()}
      <div class="rg-nav"><button class="btn" type="button" data-act="reg-back">Назад</button><button class="btn pri" type="button" data-act="reg-finish">Завершить регистрацию</button></div>
    </div>`;
  const errN = Object.keys(r.errors).length;
  return `<div class="wrap page">${crumbs(["#cabinet", r.edit ? "Данные компании" : "Регистрация"])}
    <div class="rg">
      <div class="rg-head"><h1 class="h1">${r.edit ? "Изменение данных компании" : "Регистрация представителя компании"}</h1>${r.edit ? "" : bar}</div>
      ${errN ? `<div class="note warn" role="alert">Исправьте поля, отмеченные красным: ${errN}.</div>` : ""}
      ${body}
    </div></div>`;
}
// Переход к следующему шагу с проверкой
async function regNext() {
  const r = UI.reg;
  r.errors = regValidate(r.step);
  if (Object.keys(r.errors).length) { render(); $(".has-err input, .has-err")?.scrollIntoView({ block: "center" }); return; }
  if (r.step === 2) { r.co.kpp = (r.co.kpp || "").toUpperCase(); }
  if (r.edit) { await regSave(); return; }
  r.step++; render(); window.scrollTo(0, 0);
}
// Сохранение регистрации в профиль
async function regSave() {
  const r = UI.reg, p = App.profile;
  p.account = { ...r.acc, registered_at: p.account?.registered_at || nowIso() };
  p.company = { ...r.co, base_id: r.from?.id || null, from_base: r.fromKeys, status: "На проверке у модератора", updated_at: nowIso() };
  if (r.from?.id && !p.companies.some((x) => x.company_id === r.from.id)) p.companies.push({ company_id: r.from.id, role: r.acc.position || "Представитель", status: "Ожидает подтверждения модератором" });
  p.notify = p.notify || defaultNotify();
  notice("moderation", r.edit ? "Изменения отправлены на проверку" : "Данные компании отправлены на проверку", `${r.co.name}: модератор регионального отделения сверит реквизиты с выпиской ЕГРЮЛ и подтвердит ваши права.`, "#cabinet.company");
  await Store.saveProfile();
  const edit = r.edit; UI.reg = null; UI.cabinetTab = "company";
  toast(edit ? "Данные компании сохранены и отправлены на проверку." : "Регистрация завершена. Данные компании отправлены модератору на проверку.");
  location.hash = "#cabinet"; render();
}

/* ---------- Уведомления: Telegram и ВКонтакте ---------- */
const NOTIFY_CHANNELS = [
  ["telegram", "Telegram", "@username или числовой ID чата", `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M21.9 4.3 18.7 19.5c-.2 1.1-.9 1.3-1.8.8l-4.9-3.6-2.4 2.3c-.3.3-.5.5-1 .5l.3-5 9.1-8.2c.4-.4-.1-.6-.6-.2L6.2 13.2l-4.8-1.5c-1-.3-1.1-1 .2-1.5L20.5 2.9c.9-.3 1.7.2 1.4 1.4z"/></svg>`],
  ["vk", "ВКонтакте", "vk.com/имя или id123456", `<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12.8 18.2C6.4 18.2 2.7 13.8 2.5 6.4h3.2c.1 5.4 2.5 7.7 4.4 8.2V6.4h3v4.7c1.9-.2 3.9-2.3 4.5-4.7h3c-.5 2.9-2.6 5-4.1 5.9 1.5.7 3.9 2.5 4.8 5.9h-3.3c-.7-2.3-2.5-4-4.9-4.2v4.2h-.3z"/></svg>`],
];
const NOTIFY_EVENTS = [
  ["new_requests", "Новые заявки по профилю компании", "Покупатели ищут то, что вы производите"],
  ["responses", "Отклики на мои заявки и предложения", ""],
  ["messages", "Новые сообщения", ""],
  ["risks", "Новые риски у предприятий из избранного", "Ликвидация, расхождения в реквизитах и т. п."],
  ["moderation", "Проверка компании модератором", "Подтверждение или запрос документов"],
];
function defaultNotify() {
  return { channels: Object.fromEntries(NOTIFY_CHANNELS.map(([k]) => [k, { on: false, contact: "" }])),
    events: Object.fromEntries(NOTIFY_EVENTS.map(([k]) => [k, Object.fromEntries(NOTIFY_CHANNELS.map(([c]) => [c, true]))])) };
}
// Приведение контакта к единому виду; null, если формат не распознан
function notifyContact(ch, v) {
  v = String(v || "").trim(); if (!v) return "";
  if (ch === "telegram") { if (/^-?\d{5,15}$/.test(v)) return v; const m = v.replace(/^https?:\/\/t\.me\//, "").replace(/^@/, ""); return /^[A-Za-z][A-Za-z0-9_]{4,31}$/.test(m) ? "@" + m : null; }
  if (ch === "vk") { const m = v.replace(/^https?:\/\/(m\.)?vk\.(com|ru)\//, "").replace(/^@/, ""); return /^(id\d+|[A-Za-z0-9_.]{2,32})$/.test(m) ? m : null; }
  return v;
}
function notifyPanel() {
  const n = App.profile.notify || (App.profile.notify = defaultNotify());
  const st = (c) => !c.on ? ["off", "Выключено"] : !c.contact ? ["warn", "Укажите контакт"] : ["on", "Включено"];
  return `<div class="nt">
    <div class="nt-channels">${NOTIFY_CHANNELS.map(([k, t, ph, ic]) => { const c = n.channels[k]; const [sc, stt] = st(c); return `<section class="nt-ch ${k} ${c.on ? "is-on" : ""}">
      <header><span class="nt-ic">${ic}</span><div><h3>${t}</h3><span class="nt-st ${sc}">${stt}</span></div>
        <label class="sw" title="${c.on ? "Выключить" : "Включить"} ${t}"><input type="checkbox" role="switch" data-nch="${k}" ${c.on ? "checked" : ""} aria-label="Уведомления в ${t}"><span></span></label></header>
      <div class="field"><label for="nt-${k}">${k === "telegram" ? "Аккаунт Telegram" : "Страница ВКонтакте"}</label>
        <input class="inp" id="nt-${k}" data-ncontact="${k}" value="${esc(c.contact)}" placeholder="${ph}" ${c.on ? "" : "disabled"} autocomplete="off"></div>
    </section>`; }).join("")}</div>
    <div class="tbl-wrap nt-ev"><table class="tbl"><thead><tr><th>Событие</th>${NOTIFY_CHANNELS.map(([, t]) => `<th>${t}</th>`).join("")}</tr></thead><tbody>
      ${NOTIFY_EVENTS.map(([k, t, d]) => `<tr><td>${t}${d ? `<div class="muted">${d}</div>` : ""}</td>${NOTIFY_CHANNELS.map(([c, ct]) => `<td><label class="sw sm"><input type="checkbox" role="switch" data-nev="${k}:${c}" ${n.events[k]?.[c] ? "checked" : ""} ${n.channels[c].on ? "" : "disabled"} aria-label="${t}: ${ct}"><span></span></label></td>`).join("")}</tr>`).join("")}
    </tbody></table></div>
    <p class="muted nt-note">Сообщения отправляет сервер платформы через Telegram Bot API и API ВКонтакте. Чтобы бот мог писать вам, после запуска сервера нужно будет один раз отправить ему команду /start. В этой версии сайта настройки сохраняются, а доставка включится вместе с сервером (этап 1 плана развития).</p>
  </div>`;
}

/* ---------- Уведомления на сайте: лента в кабинете, дублирование в Telegram и ВКонтакте ---------- */
// Каналы, куда уйдёт копия уведомления по текущим настройкам пользователя
function notifyVia(ev) {
  const n = App.profile.notify || defaultNotify();
  return NOTIFY_CHANNELS.map(([c]) => c).filter((c) => n.channels[c]?.on && n.channels[c]?.contact && n.events[ev]?.[c]);
}
// Новое уведомление: всегда в ленту на сайте, копия в мессенджеры по настройкам
function notice(ev, title, text, link) {
  const box = App.profile.inbox || (App.profile.inbox = []);
  box.unshift({ id: uidGen(), ev, title, text, link: link || "", at: nowIso(), read: false, via: notifyVia(ev) });
  App.profile.inbox = box.slice(0, 100);
}
// Проверка событий по свежим данным: новые заявки по профилю, отклики, новые риски у избранных.
// При первом запуске текущее состояние запоминается без уведомлений, чтобы не завалить ленту старыми событиями.
function syncNotices() {
  const p = App.profile;
  if (!App.data || !p.account) return;
  const first = !p.seen;
  const seen = p.seen || (p.seen = { req: [], resp: [], risk: {} });
  const before = (p.inbox || []).length + seen.req.length + seen.resp.length + JSON.stringify(seen.risk).length;
  const base = p.company?.base_id;
  for (const r of App.requests) {
    if (seen.req.includes(r.id)) continue;
    seen.req.push(r.id);
    if (first || r.author === App.uid || !base) continue;
    if (searchCompanies(requestQuery(r)).some((m) => m.c.id === base)) notice("new_requests", "Новая заявка по профилю вашей компании", r.what, "#r." + r.id);
  }
  for (const r of App.requests.filter((x) => x.author === App.uid)) {
    responsesOf(r).forEach((x) => {
      const k = x.key;
      if (seen.resp.includes(k)) return;
      seen.resp.push(k);
      if (!first && x.author !== App.uid) notice("responses", "Новый отклик на заявку", `${x.company || "Поставщик"}: ${r.what}`, "#r." + r.id);
    });
  }
  for (const key of p.favorites.filter((k) => k.startsWith("c:"))) {
    const c = App.C[key.slice(2)]; if (!c) continue;
    const titles = companyRisks(c).risks.filter((x) => x.level !== "low").map((x) => x.title);
    const was = seen.risk[c.id];
    if (!first && was) titles.filter((t) => !was.includes(t)).forEach((t) => notice("risks", "Новый риск у предприятия из избранного", `${c.short}: ${t}`, "#c." + c.id));
    seen.risk[c.id] = titles;
  }
  const after = (p.inbox || []).length + seen.req.length + seen.resp.length + JSON.stringify(seen.risk).length;
  if (after !== before) Store.saveProfile();
}
const INBOX_IC = { new_requests: "₽", responses: "↩", messages: "✉", risks: "!", moderation: "✓" };
const chName = (c) => (NOTIFY_CHANNELS.find(([k]) => k === c) || [, c])[1];
function inboxView() {
  const box = App.profile.inbox || [];
  const unread = box.filter((x) => !x.read).length;
  return `<div class="sec-h"><h2 class="h2">Уведомления</h2><div class="row">${unread ? `<button class="btn sm" data-act="notice-read-all">Отметить все прочитанными</button>` : ""}<a class="btn sm txt" href="#cabinet.settings">Настроить Telegram и ВКонтакте</a></div></div>
    ${box.length ? `<ul class="ib">${box.map((x) => `<li class="${x.read ? "" : "new"} ${x.ev}">
      <span class="ib-ic">${INBOX_IC[x.ev] || "•"}</span>
      <div class="ib-body"><b>${esc(x.title)}</b><p>${esc(x.text)}</p>
        <div class="ib-meta"><time>${fmtDate(x.at)} ${esc(String(x.at).slice(11, 16))}</time>${x.via.length ? `<span class="ib-via">Копия: ${x.via.map(chName).join(", ")}</span>` : `<span class="ib-via off">Только на сайте</span>`}</div></div>
      <div class="ib-acts">${x.link ? `<a class="btn sm" href="${esc(x.link)}" data-act="notice-open" data-id="${esc(x.id)}">Открыть</a>` : ""}${x.read ? "" : `<button class="btn sm txt" data-act="notice-read" data-id="${esc(x.id)}">Прочитано</button>`}</div>
    </li>`).join("")}</ul>
    <p class="muted" style="margin-top:12px;max-width:760px">Копии в Telegram и ВКонтакте отправляет сервер платформы. В этой версии сайта уведомления показываются здесь, а отправка в мессенджеры включится вместе с сервером.</p>`
    : `<div class="mkt-empty" style="border:1px dashed var(--border);border-radius:12px"><b>Уведомлений пока нет</b><p>Здесь появятся новые заявки по профилю вашей компании, отклики, новые риски у предприятий из избранного и решения модератора.</p></div>`}`;
}

/* ---------- Админ-панель ---------- */
ROUTES.admin = (arg) => {
  if (arg) UI.adminTab = arg;
  if (!App.canEdit) return `<div class="wrap page">${crumbs(["#admin", "Администрирование"])}<h1 class="h1">Административная панель</h1><div class="note" style="margin-top:16px">Раздел доступен пользователям с правом редактирования платформы.</div></div>`;
  const t = UI.adminTab;
  const tabs = [["companies", "Предприятия"], ["sources", "Источники"], ["crawler", "Crawler jobs"], ["errors", "Ошибки краулера"], ["moderation", "Модерация"], ["reports", "Жалобы"], ["dict", "ОКВЭД / ОКПД2"], ["ai", "AI-индексация"], ["history", "История изменений"], ["arch", "Архитектура"]];
  let body = "";
  if (t === "companies") body = `<div class="tbl-wrap"><table class="tbl sticky"><thead><tr><th>Предприятие</th><th>ИНН</th><th>Регион</th><th>Статус</th><th>Полнота</th><th>Расхождения</th><th>Источники</th><th>Действие</th></tr></thead><tbody>
    ${App.data.companies.map((c) => `<tr><td><a href="#c.${esc(c.id)}">${esc(c.short)}</a></td><td class="num">${c.inn ? esc(c.inn) : unk("conf")}</td><td>${esc(c.city)}</td><td>${statusBadge(c.verification_status)}</td><td class="num">${completeness(c).n}/${completeness(c).of}</td><td>${(c.discrepancies || []).length}</td><td>${c.sources.length}</td>
    <td><select class="sel" aria-label="Статус" data-setstatus="${esc(c.id)}">${["VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED", "OUTDATED"].map((s) => `<option ${c.verification_status === s ? "selected" : ""}>${s}</option>`).join("")}</select></td></tr>`).join("")}
    </tbody></table></div><p class="muted">Смена статуса записывается в журнал аудита. Правка значений предприятия выполняется через Git-репозиторий данных (pull request с источником).</p>`;
  if (t === "sources") body = `<div class="tbl-wrap"><table class="tbl sticky"><thead><tr><th>Источник</th><th>Предприятие</th><th>Тип</th><th>Приоритет</th><th>Обход</th><th>Проверено</th><th>Статус</th></tr></thead><tbody>
    ${Object.values(App.S).map((s) => `<tr><td><button class="srcbtn" data-src="${esc(s.id)}">${esc(s.source_title)}</button><div class="muted">${esc(domain(s.source_url))}</div></td><td>${esc(App.C[s.company_id].short)}</td><td>${esc(s.source_type)}</td><td>${s.priority}</td><td>${s.fetch_status === "OK" ? '<span class="v yes">OK</span>' : `<span class="v no">${esc(s.fetch_status)}</span>`}</td><td>${fmtDate(s.last_verified_at)}</td>
    <td><label class="chk"><input type="checkbox" data-srcflag="${esc(s.id)}" ${srcActive(s.id) ? "checked" : ""}> Используется</label></td></tr>`).join("")}
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
  if (t === "reports") { const reps = (App.reports || []).filter((r) => r.kind === "data_error"); body = reps.length ? `<ul class="list">${reps.map((r) => `<li><span><a href="#c.${esc(r.company_id)}">${esc(App.C[r.company_id]?.short)}</a> · ${esc(r.field || "")}<br>${esc(r.text)}<br><span class="muted">${fmtDate(r.created_at)}</span></span><button class="btn sm" data-act="report-close" data-id="${esc(r.id)}">Закрыть</button></li>`).join("")}</ul>` : '<div class="note">Жалоб нет.</div>'; }
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
// Таблица модерации записей
function modTable(rows, coll, title) {
  if (!rows.length) return '<div class="note">Записей нет.</div>';
  return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Название</th><th>Дата</th><th>Статус</th><th>Действия</th></tr></thead><tbody>${rows.map((r) => `<tr><td>${esc(title(r))}</td><td>${fmtDate(r.created_at)}</td><td>${esc(r.status || "NEW")}</td><td class="row"><button class="btn sm" data-mod="${coll}:${esc(r.id)}:APPROVED">Одобрить</button><button class="btn sm danger" data-mod="${coll}:${esc(r.id)}:REJECTED">Отклонить</button></td></tr>`).join("")}</tbody></table></div>`;
}
// Раздел «Архитектура»: схемы сбора данных и работы платформы
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
