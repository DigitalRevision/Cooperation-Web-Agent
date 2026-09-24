/* ===== Личный кабинет и административная панель ===== */

/* ---------- Личный кабинет: предложения, заявки, предприятия, склады, настройки ---------- */
// Иконки кнопок в шапке кабинета
const CAB_ICON = {
  chain: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="9" width="6" height="6" rx="1"/><rect x="16" y="9" width="6" height="6" rx="1"/><path d="M8 12h8"/></svg>`,
  compare: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h13l-3-3M20 17H7l3 3"/></svg>`,
  logout: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5M21 12H9"/></svg>`,
};
ROUTES.cabinet = (arg) => {
  // Пока профиль не прочитан из хранилища, неизвестно, зарегистрирован ли пользователь: ничего не заводим, показываем загрузку.
  // Иначе при обновлении страницы кабинет успевал открыть пустую регистрацию и оставался на ней
  if (!App.profileLoaded) return `<div class="wrap page">${crumbs(["#cabinet", "Личный кабинет"])}<p class="muted">Загрузка личного кабинета…</p></div>`;
  // Без регистрации кабинет недоступен: показываем мастер регистрации
  if (!App.profile.account || UI.reg) return regView();
  // Вышел из кабинета: вход по рабочему e-mail, указанному при регистрации
  if (App.profile.signedOut) return loginView();
  if (arg) UI.cabinetTab = arg;
  const t = UI.cabinetTab;
  const unread = (App.profile.inbox || []).filter((x) => !x.read).length;
  const tabs = [["company", "Компания"], ["inbox", "Уведомления" + (unread ? ` <span class=\"tab-n\">${unread}</span>` : "")], ["offers", "Мои предложения"], ["requests", "Мои заявки"], ["companies", "Мои предприятия"], ["warehouses", "Мои склады"], ["favorites", "Избранное"], ["saved", "Сохранённые поиски"], ["messages", "Сообщения"], ["settings", "Настройки"]];
  const myOffers = App.offers.filter((o) => o.author === App.uid), myReq = App.requests.filter((r) => r.author === App.uid);
  const co = App.profile.company || {}, acc = App.profile.account;
  let body = "";
  if (t === "company") body = `<div class="sec-h"><h2 class="h2">Данные компании</h2><button class="btn" data-act="reg-edit">Изменить данные</button></div>
    <div class="co-top">
      <section class="egr"><header><h2>${esc(co.legal_name || co.name)}</h2><span class="egr-st ${co.status === "Подтверждено" ? "ok" : co.status === "Отклонено" ? "bad" : "none"}">${esc(co.status || "На проверке у модератора")}</span></header>
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
        <dl class="kv"><dt>ФИО</dt><dd>${esc(acc.fio)}</dd><dt>Должность</dt><dd>${esc(acc.position)}</dd><dt>E-mail</dt><dd>${esc(acc.email)}</dd><dt>Телефон</dt><dd>${acc.phone ? phoneHtml(acc.phone) : unk("none")}</dd><dt>Регистрация</dt><dd>${fmtDate(acc.registered_at)}</dd>
        <dt>Контакты компании</dt><dd>${[co.site && esc(co.site), co.phone && phoneHtml(co.phone), co.email && esc(co.email)].filter(Boolean).join("<br>") || unk("none")}</dd></dl></section>
    </div>
    ${moderationNote(co)}`;
  if (t === "inbox") body = inboxView();
  if (t === "offers") {
    // продукция предприятий пользователя из открытых источников: другие видят её в «Предложениях поставщиков», сам пользователь — здесь
    const own = baseOffers().filter((o) => myCompanyIds().has(o.company_id));
    // удалённые представителем позиции: исходные данные сохранены, их можно вернуть
    const removed = [...myCompanyIds()].filter(canEditProducts).flatMap((cid) => (App.C[cid]?._deleted || []).map((p) => ({ ...p, company_id: cid })));
    // позиции по компаниям: сначала компания регистрации, у каждой — есть ли права на правку и почему нет
    const groups = [...myCompanyIds()].sort((a, b) => (b === co.base_id) - (a === co.base_id))
      .map((cid) => ({ c: App.C[cid], items: own.filter((o) => o.company_id === cid) })).filter((g) => g.c && g.items.length);
    body = `<div class="sec-h"><h2 class="h2">Мои предложения (${myOffers.length})</h2><button class="btn pri" data-act="offer-new">Разместить предложение</button></div>${myOffers.map(offerRow).join("") || '<div class="note">Вы ещё не размещали предложений.</div>'}
    <section class="sec"><div class="sec-h"><h2 class="h2">Продукция компании из открытых источников (${own.length})</h2></div>
      <p class="muted" style="margin-top:0;max-width:760px">Позиции собраны с сайтов предприятий и из каталогов. Покупатели видят их в разделе «Предложения поставщиков», вам они там не показываются. Подтверждённый представитель компании может исправить название, описание, характеристики и код ОКПД2 или удалить позицию, изменения сразу видны всем.</p>
      ${groups.map(({ c, items }) => { const why = productEditBlock(c.id); return `<div class="own-group">
        <div class="own-group-h"><a href="#c.${esc(c.id)}"><b>${esc(c.name)}</b></a> <span class="muted">${items.length} ${plural(items.length, "позиция", "позиции", "позиций")}</span>
          ${why ? '<span class="v part">Изменять пока нельзя</span>' : '<span class="v yes">Вы подтверждённый представитель</span>'}</div>
        ${why ? `<p class="own-group-why">${esc(why)}</p>` : ""}
        <ul class="own-list">${items.map((o) => ownProductRow(o.p)).join("")}</ul></div>`; }).join("") || '<div class="note">Продукция вашего предприятия в открытых источниках не найдена.</div>'}
      ${removed.length ? `<h3 class="h3" style="margin:24px 0 8px">Удалённые позиции (${removed.length})</h3><ul class="own-list">${removed.map((p) => `<li class="own-p removed">
        <div class="own-p-main"><span class="own-p-name">${esc(p.name)}</span><div class="own-p-meta"><span>${esc(p.category)}</span>${myProductEdit(p.id)?.updated_at ? `<span>удалена ${fmtDate(myProductEdit(p.id).updated_at)}</span>` : ""}</div></div>
        <div class="own-p-acts"><button class="ibtn" data-act="prod-restore" data-product="${esc(p.id)}" aria-label="Вернуть «${esc(p.name)}»">${ICON.undo}Вернуть</button></div></li>`).join("")}</ul>` : ""}</section>`;
  }
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
  <div class="sec-h"><div><h1 class="h1">Личный кабинет</h1><p class="muted" style="margin:4px 0 0">${esc(acc.fio)} · ${esc(co.name || "")} · <span class="cab-st ${co.status === "Подтверждено" ? "ok" : co.status === "Отклонено" ? "bad" : ""}">${esc(co.status || "На проверке у модератора")}</span></p></div>
    <div class="row"><a class="ibtn" href="#chains">${CAB_ICON.chain}Мои цепочки<span class="cnt">${App.chains.length}</span></a><a class="ibtn" href="#compare">${CAB_ICON.compare}Сравнение<span class="cnt">${App.profile.compare.length}</span></a><button class="ibtn out" data-act="logout">${CAB_ICON.logout}Выйти</button></div></div>
  <div class="tabs" role="tablist">${tabs.map(([k, n]) => `<button role="tab" aria-selected="${t === k}" data-ctab="${k}">${n}</button>`).join("")}</div>${body}</div>`;
};

// Строка своей позиции в кабинете: название, тип и категория, код ОКПД2, отметка о правке, источник; справа действия.
// Компания и «цена по запросу» не повторяются: в своём списке они у всех позиций одинаковые
function ownProductRow(p) {
  const cid = p.company_id || p.c?.id;
  return `<li class="own-p">
    <div class="own-p-main"><a class="own-p-name" href="#p.${esc(p.id)}">${esc(p.name)}</a>
      <div class="own-p-meta"><span>${p.kind === "service" ? "Услуга" : "Продукция"} · ${esc(p.category)}</span>${p.okpd2 ? okpdTag(p.okpd2) : "<span>ОКПД2 не указан</span>"}${p.company_edit ? `<span class="st VERIFIED">Изменено ${fmtDate(p.company_edit.at)}</span>` : ""}${srcBtn(p.source_id)}</div></div>
    ${canEditProducts(cid) ? `<div class="own-p-acts">${editBtns(p)}</div>` : ""}</li>`;
}

// Статус проверки компании в кабинете: что сделал модератор и что это значит для пользователя
function moderationNote(co) {
  if (co.status === "Подтверждено") return `<div class="note" style="margin-top:16px"><b>Права представителя подтверждены</b>${co.decided_at ? ` ${fmtDate(co.decided_at)}` : ""}.
    ${co.base_id ? "Предложения от имени компании отмечаются как «Представитель компании подтверждён»." : "Компании нет в проверенной базе: предложения публикуются с пометкой «Указано пользователем»."}${co.moderator_comment ? `<br>Комментарий модератора: ${esc(co.moderator_comment)}` : ""}</div>`;
  if (co.status === "Отклонено") return `<div class="note warn" style="margin-top:16px"><b>Модератор отклонил регистрацию.</b> ${co.moderator_comment ? `Причина: ${esc(co.moderator_comment)}` : ""}
    <div class="row" style="margin-top:8px"><button class="btn sm pri" data-act="reg-edit">Исправить и отправить снова</button></div></div>`;
  return `<div class="note" style="margin-top:16px">Модератор регионального отделения сверит данные с выпиской ЕГРЮЛ и подтвердит ваши права. До подтверждения предложения от имени компании помечаются как «указано пользователем». Решение придёт в уведомления.</div>`;
}

/* ---------- Вход в личный кабинет после выхода ---------- */
// Аккаунт хранится на этом устройстве (или в профиле claude.ai); вход — по рабочему e-mail из регистрации
function loginView() {
  const err = UI.loginErr;
  return `<div class="wrap page">${crumbs(["#cabinet", "Вход"])}
    <div class="rg"><div class="rg-head"><h1 class="h1">Вход в личный кабинет</h1></div>
      <form id="login-form" class="rg-card" novalidate>
        <p class="muted">Вы вышли из личного кабинета. Чтобы войти, укажите рабочий e-mail, который вы указали при регистрации.</p>
        <div class="form"><div class="field full${err ? " has-err" : ""}"><label for="lg-email">Рабочий e-mail</label>
          <input class="inp" id="lg-email" name="email" type="email" autocomplete="email" required value="${esc(UI.loginEmail || "")}">
          ${err ? `<span class="rg-err">${esc(err)}</span>` : ""}</div></div>
        <div class="rg-nav"><button class="btn" type="button" data-act="reg-new">Зарегистрировать другую компанию</button><button class="btn pri" type="submit">Войти</button></div>
      </form></div></div>`;
}

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
    if ((r.acc.phone || "").trim() && !parsePhone(r.acc.phone)) e["acc.phone"] = "Российский номер: 10 цифр после +7, например +7 (777) 777-77-77";
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
    if (v("phone") && !parsePhone(v("phone"))) e["co.phone"] = "Российский номер: 10 цифр после +7, например +7 (8442) 98-85-91";
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
      reg_date: c.reg_date ? fmtDate(c.reg_date) : "", address: c.address, site: c.site, phone: c.phones[0] && fmtPhone(c.phones[0]), email: c.emails[0] };
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
    <input class="inp${fromBase ? " from-base" : ""}" id="rg-${scope}-${k}" data-rf="${scope}.${k}" value="${esc(val)}" ${hint ? `placeholder="${esc(hint)}"` : ""} ${req ? "required" : ""} ${["inn", "ogrn", "okpo"].includes(k) ? 'inputmode="numeric"' : k === "phone" ? 'type="tel" inputmode="tel"' : ""} autocomplete="off">
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
      <div class="rg-nav">${r.fresh ? `<button class="btn" type="button" data-act="reg-cancel">Отмена</button>` : "<span></span>"}<button class="btn pri" type="submit">Далее: компания</button></div>
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
  // регистрация другой компании после выхода: настройки уведомлений прежнего пользователя не показываем
  if (r.step === 3 && r.fresh && !r.notifyReset) { App.profile.notify = defaultNotify(); r.notifyReset = true; }
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
// Сохранение регистрации в профиль и отправка модератору.
// Профиль лежит в личном разделе пользователя; модератору уходит копия в коллекцию registrations (её видят только
// сам пользователь и модераторы). Каждая отправка — новая заявка на проверку: решение по прошлой к ней не относится
async function regSave() {
  const r = UI.reg, p = App.profile, submitted = nowIso();
  if (r.acc.phone) r.acc.phone = fmtPhone(r.acc.phone);
  if (r.co.phone) r.co.phone = fmtPhone(r.co.phone);
  // новая регистрация после выхода: уведомления, привязки и склады прежнего пользователя не переносим
  const fresh = !r.edit && !!p.account && p.signedOut;
  if (fresh) Object.assign(p, { inbox: [], seen: null, companies: [], warehouses: [], saved: [], favorites: [], compare: [] });
  p.account = { ...r.acc, registered_at: fresh ? submitted : p.account?.registered_at || submitted };
  p.company = { ...r.co, base_id: r.from?.id || null, from_base: r.fromKeys, status: "На проверке у модератора", submitted_at: submitted, updated_at: submitted };
  p.signedOut = false;
  const claim = r.from?.id && p.companies.find((x) => x.company_id === r.from.id);
  if (claim) claim.status = "Ожидает подтверждения модератором";
  else if (r.from?.id) p.companies.push({ company_id: r.from.id, role: r.acc.position || "Представитель", status: "Ожидает подтверждения модератором" });
  p.notify = p.notify || defaultNotify();
  const { fio, position, email, phone } = p.account;
  await Store.put("registrations", App.uid, { account: { fio, position, email, phone: phone || "" }, company: { ...r.co }, base_id: r.from?.id || null,
    from_base: r.fromKeys, status: "PENDING", submitted_at: submitted, edit: !!r.edit });
  notice("moderation", r.edit ? "Изменения отправлены на проверку" : "Данные компании отправлены на проверку", `${r.co.name}: модератор регионального отделения сверит реквизиты с выпиской ЕГРЮЛ и подтвердит ваши права.`, "#cabinet.company");
  await Store.saveProfile();
  const edit = r.edit; UI.reg = null; UI.cabinetTab = "company";
  toast(edit ? "Данные компании сохранены и отправлены на проверку." : "Регистрация завершена. Данные компании отправлены модератору на проверку.");
  location.hash = "#cabinet"; render();
}

// Регистрации, сделанные до появления очереди модерации, хранились только в профиле пользователя, и модератор их не видел.
// Отправляем такую регистрацию в очередь один раз: после отправки в профиле появляется submitted_at.
// На этом устройстве (без общего хранилища) очередь читается сразу, поэтому потерянная копия тоже восстанавливается
let _regSubmitting = false;
async function ensureRegistrationSubmitted() {
  const p = App.profile, co = p.company;
  if (_regSubmitting || !App.uid || !p.account || !co || co.status !== "На проверке у модератора") return;
  if (co.submitted_at && !(App.mode === "local" && !App.registrations.some((r) => r.id === App.uid))) return;
  _regSubmitting = true;
  try {
    const submitted = co.submitted_at || co.updated_at || p.account.registered_at || nowIso();
    const { fio, position, email, phone } = p.account;
    const { base_id, from_base, status, submitted_at, updated_at, moderator_comment, decided_at, ...company } = co;
    const ok = await Store.put("registrations", App.uid, { account: { fio, position, email, phone: phone ? fmtPhone(phone) : "" }, company,
      base_id: base_id || null, from_base: from_base || [], status: "PENDING", submitted_at: submitted, edit: false });
    if (ok && !co.submitted_at) { co.submitted_at = submitted; await Store.saveProfile(); }
  } finally { _regSubmitting = false; }
}

/* ---------- Продукция из открытых источников: правка и удаление представителем компании ---------- */
function openProductEdit(pid) {
  const p = App.P[pid]; if (!p || !canEditProducts(p.company_id)) return;
  const params = (p.params || []).map((x) => (x.value ? `${x.name}: ${x.value}` : x.name)).join("\n");
  const cur = p.okpd2?.code || "";
  const codes = Object.entries(App.data.okpd2).sort(([a], [b]) => a.localeCompare(b));
  openPanel(`<div class="panel-h"><div><div class="label">Продукция компании</div><h2 class="h2">Изменить позицию</h2></div><button class="x" data-close aria-label="Закрыть">×</button></div>
  <form id="product-edit-form" class="form" data-product="${esc(pid)}" novalidate>
    <div class="field full"><label for="pe-name">Название *</label><input class="inp" id="pe-name" name="name" required maxlength="200" value="${esc(p.name)}"></div>
    <div class="field"><label for="pe-kind">Тип</label><select class="sel" id="pe-kind" name="kind"><option value="product" ${p.kind !== "service" ? "selected" : ""}>Продукция</option><option value="service" ${p.kind === "service" ? "selected" : ""}>Производственная услуга</option></select></div>
    <div class="field"><label for="pe-cat">Категория</label><input class="inp" id="pe-cat" name="category" maxlength="100" value="${esc(p.category)}"></div>
    <div class="field"><label for="pe-country">Страна производства</label><input class="inp" id="pe-country" name="country" list="pe-countries" maxlength="60" value="${esc(productCountry(p))}"><datalist id="pe-countries">${COUNTRIES.map((x) => `<option value="${esc(x)}">`).join("")}</datalist></div>
    <div class="field full"><label for="pe-okpd">Код ОКПД2</label><select class="sel" id="pe-okpd" name="okpd2"><option value="">Не указан</option>${codes.map(([k, v]) => `<option value="${esc(k)}" ${k === cur ? "selected" : ""}>${esc(k)} — ${esc(v.slice(0, 70))}</option>`).join("")}</select>
      <span class="muted">Выбранный код отмечается как подтверждённый предприятием и учитывается в подборе поставщиков.</span></div>
    <div class="field full"><label for="pe-desc">Описание</label><textarea class="inp" id="pe-desc" name="description" maxlength="2000">${esc(p.description || "")}</textarea></div>
    <div class="field full"><label for="pe-params">Характеристики</label><textarea class="inp" id="pe-params" name="params" placeholder="Параметр: значение — по одному на строку">${esc(params)}</textarea></div>
    <div class="full note">Изменения сразу видны всем пользователям с пометкой «Изменено представителем компании». Исходные данные из открытых источников сохраняются.</div>
    <div class="full row"><button class="btn pri" type="submit">Сохранить</button><button class="btn" type="button" data-close>Отмена</button></div>
  </form>`);
}
// Разбор полей формы: пустое — не указано; характеристики — «Параметр: значение» по строкам, не больше 30
function productFields(d) {
  const params = String(d.params || "").split("\n").map((l) => l.trim()).filter(Boolean).slice(0, 30).map((l) => {
    const i = l.indexOf(":");
    return i > 0 ? { name: l.slice(0, i).trim(), value: l.slice(i + 1).trim() || null } : { name: l, value: null };
  });
  const code = String(d.okpd2 || "");
  return { name: String(d.name || "").trim().slice(0, 200), kind: d.kind === "service" ? "service" : "product", category: String(d.category || "").trim().slice(0, 100) || "Без категории",
    description: String(d.description || "").trim().slice(0, 2000) || null, params, country: String(d.country || "").trim().slice(0, 60) || "Россия", okpd2: App.data.okpd2[code] ? { code, name: App.data.okpd2[code], status: "COMPANY" } : null };
}
function confirmProductDelete(pid) {
  const p = App.P[pid]; if (!p || !canEditProducts(p.company_id)) return;
  openPanel(`<div class="panel-h"><div><div class="label">Продукция компании</div><h2 class="h2">Удалить позицию?</h2></div><button class="x" data-close aria-label="Закрыть">×</button></div>
    <p>«${esc(p.name)}» пропадёт из каталога продукции, предложений поставщиков и подбора. Вернуть позицию можно в личном кабинете, во вкладке «Мои предложения».</p>
    <div class="row" style="margin-top:16px"><button class="btn danger" data-act="prod-del-confirm" data-product="${esc(pid)}">Удалить</button><button class="btn" type="button" data-close>Отмена</button></div>`, "narrow");
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
  seen.mod = seen.mod || {};
  const before = (p.inbox || []).length + seen.req.length + seen.resp.length + JSON.stringify(seen.risk).length + JSON.stringify(seen.mod).length;
  const base = p.company?.base_id;
  for (const r of shownToAll("requests")) {
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
  // Решение модератора по текущей отправке регистрации: статус компании в кабинете и уведомление
  // (в ленту на сайте всегда, в Telegram и ВКонтакте — по настройкам, отправляет сервер уведомлений)
  const dec = p.company?.submitted_at && App.moderation.find((x) => x.id === App.uid && x.submitted_at === p.company.submitted_at);
  if (dec && p.company.decided_at !== dec.decided_at) {
    const ok = dec.status === "APPROVED";
    Object.assign(p.company, { status: ok ? "Подтверждено" : "Отклонено", moderator_comment: dec.comment || "", decided_at: dec.decided_at });
    const claim = p.companies.find((x) => x.company_id === p.company.base_id);
    if (claim) claim.status = ok ? "Подтверждено модератором" : "Отклонено модератором";
    notice("moderation", ok ? "Компания подтверждена модератором" : "Регистрация отклонена модератором",
      `${p.company.name}: ` + (ok ? "данные компании и права представителя подтверждены." : "регистрация отклонена." + (dec.comment ? ` Причина: ${dec.comment}` : "")), "#cabinet.company");
  }
  // Решения модератора по предложениям и заявкам пользователя: уведомление автору (повторно не приходит)
  for (const coll of ["offers", "requests"]) for (const x of App[coll].filter((x) => x.author === App.uid)) {
    const d = itemDecision(coll, x);
    if (!d || d.legacy) continue;
    const key = coll + ":" + x.id, known = key in seen.mod;
    if (seen.mod[key] === d.decided_at) continue;
    seen.mod[key] = d.decided_at;
    if (first && !known) continue;
    const ok = d.status === "APPROVED", offer = coll === "offers", title = offer ? x.title : x.what;
    notice("moderation", offer ? `Предложение ${ok ? "одобрено" : "отклонено"} модератором` : `Заявка ${ok ? "одобрена" : "отклонена"} модератором`,
      `«${title}»: ` + (ok ? (offer ? "проверено и отмечено для покупателей как проверенное." : "проверена, поставщики видят её с пометкой «Проверено модератором».")
        : (offer ? "предложение скрыто из общего списка." : "заявка скрыта из общего списка.") + (d.comment ? ` Причина: ${d.comment}` : "")),
      offer ? "#cabinet.offers" : "#r." + x.id);
  }
  const after = (p.inbox || []).length + seen.req.length + seen.resp.length + JSON.stringify(seen.risk).length + JSON.stringify(seen.mod).length;
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
        <div class="ib-meta"><time>${fmtDate(x.at)} ${esc(String(x.at).slice(11, 16))}</time>${x.via.length ? `<span class="ib-via" title="Копию отправляет сервер уведомлений платформы">Копия в ${esc(x.via.map(chName).join(", "))}</span>` : `<span class="ib-via off">Только на сайте</span>`}</div></div>
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
  const pendingRegs = App.registrations.filter((r) => !decisionFor(r)).length;
  const tabs = [["companies", "Предприятия"], ["sync", "Сбор данных"], ["sources", "Источники"], ["crawler", "Обход сайтов"], ["errors", "Ошибки обхода"],
    ["moderation", "Модерация" + (pendingRegs ? ` <span class="tab-n">${pendingRegs}</span>` : "")], ["reports", "Жалобы"], ["dict", "ОКВЭД / ОКПД2"], ["history", "История изменений"], ["arch", "Архитектура"]];
  let body = "";
  if (t === "companies") body = adminCompanies();
  if (t === "sync") body = syncPanel();
  if (t === "sources") body = `<div class="tbl-wrap"><table class="tbl sticky"><thead><tr><th>Источник</th><th>Предприятие</th><th>Тип</th><th>Приоритет</th><th>Обход</th><th>Проверено</th><th>Использование</th></tr></thead><tbody>
    ${Object.values(App.S).map((s) => `<tr><td><button class="srcbtn" data-src="${esc(s.id)}">${esc(s.source_title)}</button><div class="muted">${esc(domain(s.source_url))}</div></td><td>${esc(App.C[s.company_id].short)}</td><td>${esc(sourceTypeTxt(s.source_type))}</td><td>${esc(s.priority)}</td><td>${s.fetch_status === "OK" ? '<span class="v yes">Прочитан</span>' : `<span class="v no">${esc(fetchTxt(s.fetch_status))}</span>`}</td><td>${fmtDate(s.last_verified_at)}</td>
    <td><label class="chk"><input type="checkbox" data-srcflag="${esc(s.id)}" ${srcActive(s.id) ? "checked" : ""}> Используется</label></td></tr>`).join("")}
    </tbody></table></div><p class="muted">Отключённый источник исключается из сопоставления: позиции продукции, подтверждённые только им, не попадают в результаты поиска.</p>`;
  if (t === "crawler" || t === "errors") {
    const log = App.data.crawl_log.filter((x) => t === "crawler" || x.status !== "OK");
    const queued = (App.reports || []).filter((r) => r.kind === "recrawl");
    body = `${t === "crawler" ? `<div class="grid3" style="margin-bottom:16px"><div class="stat"><b class="num">${App.data.crawl_log.length}</b><span class="muted">запросов в задании 24.09.2026</span></div><div class="stat"><b class="num">${App.data.crawl_log.filter((x) => x.status === "OK").length}</b><span class="muted">успешно прочитано</span></div><div class="stat"><b class="num">${App.data.crawl_log.filter((x) => x.status !== "OK").length}</b><span class="muted">ошибок (доступ запрещён, правила обхода, перенаправления)</span></div></div>` : ""}
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>Адрес</th><th>Результат</th><th>Комментарий</th><th>Дата</th><th></th></tr></thead><tbody>
    ${log.map((x) => `<tr><td style="overflow-wrap:anywhere"><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.url)}</a></td><td>${x.status === "OK" ? '<span class="v yes">Прочитан</span>' : `<span class="v no">${esc(fetchTxt(x.status))}</span>`}</td><td>${esc(x.note)}</td><td>${fmtDate(x.fetched_at)}</td><td><button class="btn sm" data-act="recrawl" data-url="${esc(x.url)}">Повторить обход</button></td></tr>`).join("")}
    </tbody></table></div>
    ${queued.length ? `<h3 class="h3" style="margin:24px 0 8px">Очередь повторного обхода (${queued.length})</h3><ul class="list">${queued.map((q) => `<li><span style="overflow-wrap:anywhere">${esc(q.url)}</span><span class="muted">поставлено ${fmtDate(q.created_at)} · ожидает воркер crawler</span></li>`).join("")}</ul>` : ""}
    <p class="muted">Воркер обхода (Scrapy + очередь Redis) соблюдает robots.txt, ограничивает частоту запросов и повторяет только временные ошибки. В этом прототипе очередь хранится на платформе, а воркер запускается из репозитория <code>crawler/</code>.</p>`;
  }
  if (t === "moderation") body = adminModeration();
  if (t === "reports") { const reps = (App.reports || []).filter((r) => r.kind === "data_error"); body = reps.length ? `<ul class="list">${reps.map((r) => `<li><span><a href="#c.${esc(r.company_id)}">${esc(App.C[r.company_id]?.short)}</a> · ${esc(r.field || "")}<br>${esc(r.text)}<br><span class="muted">${fmtDate(r.created_at)}</span></span><button class="btn sm" data-act="report-close" data-id="${esc(r.id)}">Закрыть</button></li>`).join("")}</ul>` : '<div class="note">Жалоб нет.</div>'; }
  if (t === "dict") body = `<div class="grid2"><div><h3 class="h3" style="margin-bottom:8px">ОКВЭД (${Object.keys(App.data.okved).length})</h3><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Код</th><th>Наименование</th><th>Предприятий</th></tr></thead><tbody>${Object.entries(App.data.okved).map(([k, v]) => `<tr><td>${okvedTag(k)}</td><td>${esc(v)}</td><td class="num">${App.data.companies.filter((c) => c.okved_main === k).length}</td></tr>`).join("")}</tbody></table></div></div>
    <div><h3 class="h3" style="margin-bottom:8px">ОКПД2 (${Object.keys(App.data.okpd2).length})</h3><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Класс</th><th>Наименование</th><th>Позиций</th></tr></thead><tbody>${Object.entries(App.data.okpd2).map(([k, v]) => `<tr><td><span class="code okpd2"><span>${esc(k)}</span></span></td><td>${esc(v)}</td><td class="num">${Object.values(App.P).filter((p) => p.okpd2?.code === k).length}</td></tr>`).join("")}</tbody></table></div>
    <p class="muted">Все коды ОКПД2 в базе присвоены по классификатору и ждут подтверждения предприятием или по ГИСП.</p></div></div>`;
  if (t === "history") { const aud = (App.reports || []).filter((r) => r.kind === "audit").sort((a, b) => (b.created_at || "").localeCompare(a.created_at || "")); body = `<ul class="list">${aud.map((a) => `<li><span>${esc(a.text)}</span><span class="muted">${fmtDate(a.created_at)}</span></li>`).join("")}<li><span>Первичный сбор: ${App.data.companies.length} предприятий, ${Object.keys(App.P).length} позиций, ${Object.keys(App.S).length} источников</span><span class="muted">${fmtDate(App.data.generated_at)} · crawler</span></li></ul>`; }
  if (t === "arch") body = archHtml();
  return `<div class="wrap page">${crumbs(["#admin", "Администрирование"])}
  <h1 class="h1">Административная панель</h1>
  <div class="tabs" role="tablist" style="margin-top:16px">${tabs.map(([k, n]) => `<button role="tab" aria-selected="${t === k}" data-atab="${k}">${n}</button>`).join("")}</div>${body}</div>`;
};

/* ---------- Сбор данных из реестров: расписание, ручной запуск, ход и итоги ---------- */
// Состояние берётся у API платформы (/api/v1/admin/sync): сайт открыт с сервера платформы (docker compose up → http://localhost:8080).
// Без сервера (файл, публикация на claude.ai) кнопка недоступна, а итоги последнего сбора показываются по базе сайта
const SYNC_REGIONS = ["Волгоградская область", "Астраханская область", "Ростовская область", "Саратовская область", "Воронежская область", "Республика Калмыкия"];
const SYNC_OKVED = [["24", "металлургия"], ["25", "металлоизделия"], ["26", "электронные компоненты"], ["27", "электрооборудование"],
  ["28", "машины и оборудование"], ["29–30", "транспортное машиностроение"], ["33", "ремонт и монтаж оборудования"]];
// без указанного токена — локальный dev-admin: работает только на своём компьютере, где PK_TOKENS не задан
const apiToken = () => LS.get("apitoken", "") || "dev-admin";
async function syncApi(method, url) {
  const r = await fetch(url, { method, headers: { Authorization: "Bearer " + apiToken(), "Content-Type": "application/json" } });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(body.detail || `Ошибка сервера (${r.status})`), { status: r.status });
  return body;
}
async function refreshSync() {
  const s = UI.sync || (UI.sync = {});
  s.loading = true;
  try { s.state = await syncApi("GET", "/api/v1/admin/sync"); s.error = null; }
  catch (e) { s.state = null; s.error = e.status === 401 || e.status === 403 ? "auth" : "offline"; }
  s.loading = false; s.checked = Date.now();
  if (route().name === "admin" && UI.adminTab === "sync") rerender();
}
// Пока вкладка открыта, состояние обновляется раз в 10 секунд
let _syncTimer = 0;
function watchSync() {
  if (_syncTimer) return;
  refreshSync();
  _syncTimer = setInterval(() => {
    if (route().name !== "admin" || UI.adminTab !== "sync") { clearInterval(_syncTimer); _syncTimer = 0; return; }
    refreshSync();
  }, 10000);
}
async function startSync() {
  const s = UI.sync || (UI.sync = {});
  s.starting = true; rerender();
  try { const r = await syncApi("POST", "/api/v1/admin/sync/run"); s.state = r; toast(r.message || "Сбор запущен."); audit("Запущен сбор данных из реестров вручную"); }
  catch (e) { toast(e.status === 409 ? "Сбор уже идёт." : e.status === 401 || e.status === 403 ? "Нужен токен администратора API." : e.message || "Сервер платформы недоступен."); }
  s.starting = false; refreshSync();
}
const dt = (iso) => (iso ? `${fmtDate(iso)} ${esc(String(iso).slice(11, 16))}` : "—");
function syncPanel() {
  watchSync();
  const s = UI.sync || {}, st = s.state, run = st?.running;
  const last = st?.last_run || (App.data.sync ? { at: App.data.sync.at, finished: App.data.sync.finished, found: App.data.sync.found, queued_new: App.data.sync.queued_new, stats: App.data.sync.stats } : null);
  const pct = run && st.total ? Math.round((st.done || 0) / st.total * 100) : 0;
  const offline = s.error === "offline", auth = s.error === "auth";
  return `<div class="sync-grid">
    <section class="card">
      <div class="card-head"><div><div class="label">Сбор из реестров ФНС и Федресурса</div><h2 class="h2">${run ? "Идёт сбор" : "Расписание"}</h2></div>
        <span class="st ${run ? "USER" : st?.daemon_alive ? "VERIFIED" : "UNVERIFIED"}">${run ? "Выполняется" : st?.daemon_alive ? "Планировщик работает" : st ? "Планировщик не запущен" : "Нет связи с сервером"}</span></div>
      ${run ? `<dl class="kv" style="margin-top:12px"><dt>Этап</dt><dd>${esc(st.stage || "подготовка")}</dd>
          <dt>Проверено</dt><dd>${st.total ? `${(st.done || 0).toLocaleString("ru-RU")} из ${st.total.toLocaleString("ru-RU")} компаний · ${pct}%` : "идёт поиск новых компаний"}</dd>
          <dt>Запуск</dt><dd>${dt(st.started_at)} · ${esc(st.trigger || "")}</dd></dl>
        ${st.total ? `<div class="prog" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${pct}"><i style="width:${pct}%"></i></div>` : ""}`
      : `<dl class="kv" style="margin-top:12px"><dt>Автоматически</dt><dd>каждый день в ${esc(st?.schedule || "00:01")}</dd>
          <dt>Следующий запуск</dt><dd>${st?.next_run ? dt(st.next_run) : unk("na")}</dd>
          ${st?.request_pending ? `<dt>Ручной запуск</dt><dd>в очереди, начнётся в течение 15 секунд</dd>` : ""}</dl>`}
      <div class="row" style="margin-top:16px">
        <button class="btn pri" data-act="sync-run" ${run || s.starting || !st ? "disabled" : ""}>${s.starting ? "Запускаем…" : "Запустить сбор сейчас"}</button>
        <button class="ibtn" data-act="sync-refresh">${s.loading ? "Обновляем…" : "Обновить"}</button>
      </div>
      ${offline ? `<div class="note warn" style="margin-top:12px">Сайт открыт без сервера платформы, поэтому кнопка и ход сбора недоступны. Запустите <code>start-local.cmd</code> из папки проекта: сайт откроется на http://localhost:8765, и кнопка заработает. Итоги ниже взяты из базы сайта.</div>` : ""}
      ${auth ? `<div class="note warn" style="margin-top:12px">Сервер отказал в доступе: укажите токен администратора API ниже.</div>` : ""}
      ${st && !st.daemon_alive && !run ? `<p class="muted" style="margin-top:12px">Планировщик (<code>python -m sync --daemon</code>) не запущен: по кнопке сервер запустит сбор сам, но ежедневный запуск в 00:01 не состоится.</p>` : ""}
      ${st?.error ? `<div class="note warn" style="margin-top:12px">Прошлый сбор завершился с ошибкой: ${esc(st.error)}</div>` : ""}
    </section>
    <section class="card">
      <div class="label">Последний сбор</div>
      ${last ? `<dl class="kv" style="margin-top:8px"><dt>Когда</dt><dd>${dt(last.at)} – ${esc(String(last.finished || "").slice(11, 16))}${st?.last_trigger ? ` · ${esc(st.last_trigger)}` : ""}</dd>
          <dt>Найдено в реестрах</dt><dd>${(last.found || 0).toLocaleString("ru-RU")} организаций</dd>
          <dt>Проверено</dt><dd>${(last.stats?.checked || 0).toLocaleString("ru-RU")}</dd>
          <dt>Добавлено новых</dt><dd>${(last.stats?.added || 0).toLocaleString("ru-RU")}${last.queued_new ? ` · ещё ${last.queued_new.toLocaleString("ru-RU")} в очереди` : ""}</dd>
          <dt>Обновлено</dt><dd>${last.stats?.updated || 0} · закрылись: ${last.stats?.closed || 0} · новых рисков: ${last.stats?.risks_added || 0}</dd>
          <dt>Не ответили источники</dt><dd>${last.stats?.failed || 0}</dd></dl>` : `<p class="muted">Сбор ещё не выполнялся.</p>`}
    </section>
    <section class="card">
      <div class="label">Что собирается</div>
      <dl class="kv" style="margin-top:8px"><dt>Регионы</dt><dd>${SYNC_REGIONS.join(", ")}</dd>
        <dt>Отрасли (ОКВЭД)</dt><dd>${SYNC_OKVED.map(([k, n]) => `${k} — ${n}`).join("<br>")}</dd>
        <dt>Отбор</dt><dd>действующие юрлица с выручкой за последний год больше нуля; компании без выручки не добавляются</dd>
        <dt>Проверка базы</dt><dd>ежедневно: статус ЕГРЮЛ и банкротства; раз в неделю: отчётность, «Прозрачный бизнес»; раз в месяц: открытые данные ФНС</dd></dl>
    </section>
    <section class="card">
      <div class="label">Доступ к серверу</div>
      <div class="field" style="margin-top:8px"><label for="api-token">Токен администратора API</label>
        <input class="inp" id="api-token" type="password" data-apitoken="1" value="${esc(apiToken())}" autocomplete="off" placeholder="значение из PK_TOKENS">
        <span class="muted" style="font-size:12px">Хранится только в этом браузере. На своём компьютере (start-local.cmd) поле можно не заполнять.</span></div>
    </section>
  </div>`;
}

/* ---------- Предприятия: вся база с фильтрами, сменой статуса проверки и всеми полями карточки ---------- */
const ADM_SIZE = 25;
function adminCompanies() {
  const f = UI.adm, s = f.q.trim().toLowerCase(), all = App.data.companies;
  const origin = (c) => (c.origin === "registry_sync" ? "sync" : "seed");
  const list = all.filter((c) => (!f.region || c.region === f.region) && (!f.st || c.verification_status === f.st) && (!f.origin || origin(c) === f.origin)
    && (!s || [c.name, c.legal_name, c.inn, c.ogrn, c.kpp, c.city, c.address, c.okved_main, c.subindustry].join(" ").toLowerCase().includes(s)));
  const pages = Math.max(1, Math.ceil(list.length / ADM_SIZE));
  if (f.page > pages) f.page = pages;
  const pg = list.slice((f.page - 1) * ADM_SIZE, f.page * ADM_SIZE);
  const opt = (v, t, cur) => `<option value="${esc(v)}" ${cur === v ? "selected" : ""}>${esc(t)}</option>`;
  const count = (st) => all.filter((c) => c.verification_status === st).length;
  const statusSelect = (c) => `<select class="sel" aria-label="Статус проверки: ${esc(c.short || c.name)}" data-setstatus="${esc(c.id)}">${Object.keys(STATUS_LABEL).map((st) => `<option value="${st}" title="${esc(STATUS_HINT[st])}" ${c.verification_status === st ? "selected" : ""}>${STATUS_LABEL[st]}</option>`).join("")}</select>`;
  const row = (c, i) => {
    const st = legalState(c), open = f.open === c.id;
    return `<tr><td class="num">${(f.page - 1) * ADM_SIZE + i + 1}</td>
      <td style="min-width:220px"><a href="#c.${esc(c.id)}"><b>${esc(c.name)}</b></a><div class="muted" style="font-size:12px">${esc(c.legal_name || "Полное наименование не подтверждено")}</div></td>
      <td class="num" style="white-space:nowrap">${c.inn ? `ИНН ${esc(c.inn)}<br><span class="muted">ОГРН ${esc(c.ogrn || "—")}${c.kpp ? `<br>КПП ${esc(c.kpp)}` : ""}</span>` : unk("conf")}</td>
      <td>${esc(regionName(c.region))}<div class="muted">${esc(c.city || "Город не указан")}</div></td>
      <td>${c.okved_main ? `<span class="num">${esc(c.okved_main)}</span><div class="muted" style="font-size:12px">${esc((App.data.okved[c.okved_main] || "").slice(0, 60))}</div>` : unk("none")}</td>
      <td>${st ? `<span class="egr-st ${STATE_TXT[st][0]}">${STATE_TXT[st][1]}</span>` : unk("conf")}</td>
      <td class="num">${c.products.length}</td>
      <td>${riskBadge(c)}</td>
      <td>${origin(c) === "sync" ? `Реестры ФНС<div class="muted">${fmtDate(c.added_at)}</div>` : "Первичный сбор"}</td>
      <td>${statusSelect(c)}</td>
      <td><button class="btn sm txt" data-act="adm-open" data-id="${esc(c.id)}" aria-expanded="${open}">${open ? "Скрыть" : "Все данные"}</button></td></tr>
      ${open ? `<tr><td colspan="11" style="background:var(--surface-alt)">${companyAllFields(c)}</td></tr>` : ""}`;
  };
  return `<div class="note" style="margin-bottom:16px"><b>Статус проверки данных</b> — насколько подтверждены сведения о предприятии. Его можно изменить в последнем столбце, смена попадает в историю изменений.
    <ul style="margin:8px 0 0;padding-left:18px">${Object.keys(STATUS_LABEL).map((st) => `<li><b>${STATUS_LABEL[st]}</b> (${count(st)}) — ${esc(STATUS_HINT[st].toLowerCase())}</li>`).join("")}</ul></div>
  <div class="toolbar">
    <div class="search" style="flex:1;min-width:240px"><label class="sr" for="adm-q">Поиск по базе</label><input id="adm-q" data-adm="q" value="${esc(f.q)}" placeholder="Название, ИНН, ОГРН, город, ОКВЭД"></div>
    <select class="sel" data-adm="region" aria-label="Регион">${opt("", "Все регионы", f.region)}${Object.values(App.data.regions).map((r) => opt(r.code, r.name, f.region)).join("")}</select>
    <select class="sel" data-adm="st" aria-label="Статус проверки">${opt("", "Любой статус проверки", f.st)}${Object.keys(STATUS_LABEL).map((st) => opt(st, STATUS_LABEL[st], f.st)).join("")}</select>
    <select class="sel" data-adm="origin" aria-label="Как попало в базу">${opt("", "Любое происхождение", f.origin)}${opt("seed", "Первичный сбор", f.origin)}${opt("sync", "Добавлено из реестров ФНС", f.origin)}</select>
    <button class="btn sm" data-act="adm-reset">Сбросить</button>
  </div>
  <p class="muted" style="margin:0 0 12px">В базе ${all.length} ${plural(all.length, "предприятие", "предприятия", "предприятий")}. По фильтрам: ${list.length}. Показано ${pg.length ? `${(f.page - 1) * ADM_SIZE + 1}–${(f.page - 1) * ADM_SIZE + pg.length}` : "0"}.</p>
  <div class="tbl-wrap"><table class="tbl sticky"><thead><tr><th>№</th><th>Предприятие</th><th>Реквизиты</th><th>Регион, город</th><th>Основной ОКВЭД</th><th>Юрлицо</th><th>Позиций</th><th>Риски</th><th>Как попало в базу</th><th>Статус проверки</th><th></th></tr></thead>
  <tbody>${pg.map(row).join("") || `<tr><td colspan="11" class="muted">По фильтрам ничего не найдено.</td></tr>`}</tbody></table></div>
  ${pager("adm", list.length, ADM_SIZE)}
  <p class="muted">Правка значений предприятия выполняется через Git-репозиторий данных (pull request с источником) или ежедневную синхронизацию с реестрами.</p>`;
}
// Все поля карточки предприятия, как они хранятся в базе, простыми словами
function companyAllFields(c) {
  const fin = c.registry?.finance?.[0], r = companyRisks(c);
  const list = (arr, f) => (arr || []).length ? arr.map(f).join("<br>") : unk("none");
  const fields = [
    ["Идентификатор в базе", esc(c.id)], ["Краткое наименование", esc(c.name)], ["Полное наименование", c.legal_name ? esc(c.legal_name) : unk("none")],
    ["ИНН", c.inn ? esc(c.inn) : unk("none")], ["ОГРН", c.ogrn ? esc(c.ogrn) : unk("none")], ["КПП", c.kpp ? esc(c.kpp) : unk("none")], ["ОКПО", c.okpo ? esc(c.okpo) : unk("none")],
    ["Дата регистрации", c.reg_date ? fmtDate(c.reg_date) : unk("none")], ["Статус юрлица", c.legal_status ? esc(c.legal_status) : unk("conf")],
    ["Статус проверки", `${statusBadge(c.verification_status)} <span class="muted">${esc(STATUS_HINT[c.verification_status] || "")}</span>`],
    ["Регион, город", `${esc(regionName(c.region))}, ${esc(c.city || "город не указан")}`], ["Юридический адрес", c.address ? esc(c.address) : unk("none")],
    ["Сайт", c.site ? `<a href="${esc(c.site)}" target="_blank" rel="noopener">${esc(domain(c.site))}</a>` : unk("none")],
    ["Телефоны", list(c.phones, phoneHtml)], ["E-mail", list(c.emails, esc)],
    ["Основной ОКВЭД", okvedTag(c.okved_main, true)], ["Дополнительные ОКВЭД", c.okved_extra?.length ? c.okved_extra.map((x) => okvedTag(x)).join(" ") : unk("none")],
    ["Отрасль", `${esc(c.industry)} · ${esc(c.subindustry)}`], ["Описание", c.description ? esc(c.description) : unk("na")],
    ["Продукция и услуги", list(c.products, (p) => `<a href="#p.${esc(p.id)}">${esc(p.name)}</a>`)],
    ["Технологии", list(c.technologies, (x) => esc(x.name))], ["Материалы", list(c.materials, (x) => esc(x.name))],
    ["Возможности по ОКВЭД", list(c.capabilities_declared, (x) => esc(x.name))], ["Мощности", list(c.capacities, (x) => esc(x.text))],
    ["Площадки", list(c.sites, (x) => `${esc(x.name)}: ${esc(x.address)}`)], ["Сертификаты", list(c.certificates, (x) => esc(x.name))],
    ["Риски", r.risks.length ? r.risks.map((x) => `${esc(RISK_TXT[x.level])}: ${esc(x.title)}`).join("<br>") : "Не выявлены"],
    ["Финансы", fin ? `Выручка ${fmtRub(fin.revenue)}, чистая прибыль ${fmtRub(fin.net_profit)} за ${esc(fin.year)} год` : unk("none")],
    ["Численность", c.registry?.headcount != null ? `${esc(c.registry.headcount)} чел.` : unk("none")],
    ["Расхождения источников", list(c.discrepancies, (d) => `${esc(d.field)}: ${esc(d.note)}`)],
    ["Источники", list(c.sources, (x) => `${srcBtn(x.id, sourceTypeTxt(x.source_type))} <span class="muted">${esc(fetchTxt(x.fetch_status).toLowerCase())}, ${fmtDate(x.last_verified_at)}</span>`)],
    ["Как попало в базу", c.origin === "registry_sync" ? `Добавлено из реестров ФНС ${fmtDate(c.added_at)}` : "Первичный сбор с сайтов и из выписок ЕГРЮЛ"],
    ["Последняя сверка с реестрами", c.sync?.checked_at ? fmtDate(c.sync.checked_at) : unk("none")],
    ["История изменений", list((c.history || []).slice(0, 5), (h) => `${fmtDate(h.date)} — ${esc(historyText(h))}`)],
  ];
  return `<dl class="kv" style="margin:8px 0">${fields.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
}

/* ---------- Модерация: регистрации представителей, предложения, заявки ---------- */
// Сверка заявки на регистрацию с карточкой из базы: что совпало, что нет
function regChecks(reg) {
  const co = reg.company || {}, base = reg.base_id && App.C[reg.base_id];
  const out = [];
  if (co.inn && !innOk(co.inn)) out.push(["bad", "ИНН не проходит проверку контрольной суммы"]);
  if (co.ogrn && !ogrnOk(co.ogrn)) out.push(["bad", "ОГРН не проходит проверку контрольной суммы"]);
  const prev = App.reps.find((r) => r.id === reg.id);
  if (prev && prev.company_id !== reg.base_id) out.push(["warn", `Сейчас подтверждён представителем «${App.C[prev.company_id]?.name || prev.company_name}». Подтверждение переведёт права на новую компанию, отклонение снимет их`]);
  if (base) {
    const diff = [["inn", "ИНН"], ["ogrn", "ОГРН"], ["kpp", "КПП"], ["okved_main", "Основной ОКВЭД"]]
      .filter(([k]) => base[k] && co[k] && String(base[k]).toUpperCase() !== String(co[k]).trim().toUpperCase());
    for (const [k, t] of diff) out.push(["bad", `${t}: в заявке ${co[k]}, в базе ${base[k]}`]);
    if (!diff.length) out.push(["ok", `ИНН, ОГРН, КПП и ОКВЭД совпадают с карточкой «${base.name}» (сведения ЕГРЮЛ)`]);
    const st = legalState(base);
    if (st && st !== "ACTIVE") out.push(["bad", `Юрлицо: ${STATE_TXT[st][1].toLowerCase()}`]);
  } else {
    const same = co.inn && App.data.companies.find((c) => c.inn === co.inn);
    out.push(same ? ["warn", `В базе есть компания с этим ИНН: «${same.name}». Представитель не выбрал её из подсказки`]
      : ["warn", "Компании нет в проверенной базе: сверьте реквизиты с выпиской ЕГРЮЛ вручную"]);
  }
  return out;
}
function regCard(reg) {
  const co = reg.company || {}, acc = reg.account || {}, base = reg.base_id && App.C[reg.base_id], id = reg.id;
  const kv = (rows) => `<dl class="kv">${rows.filter(([, v]) => v).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
  const cls = { ok: "yes", warn: "part", bad: "no" };
  return `<article class="card" style="margin-bottom:12px">
    <div class="card-head"><div style="min-width:0"><span class="label">${reg.edit ? "Изменение данных компании" : "Новая регистрация"} · отправлено ${fmtDate(reg.submitted_at)}</span>
      <h3 class="h3">${esc(co.name || "Компания не указана")}</h3>${base ? `<div class="muted">Карточка в базе: <a href="#c.${esc(base.id)}">${esc(base.name)}</a></div>` : ""}</div>
      <span class="st USER">Ожидает проверки</span></div>
    <ul class="list" style="margin:12px 0">${regChecks(reg).map(([k, t]) => `<li><span><span class="v ${cls[k]}">${k === "ok" ? "Совпадает" : k === "bad" ? "Расхождение" : "Проверить"}</span> ${esc(t)}</span></li>`).join("")}</ul>
    <div class="grid2">
      <div><div class="label" style="margin-bottom:6px">Компания</div>${kv([["Полное наименование", esc(co.legal_name)], ["ИНН", esc(co.inn)], ["ОГРН", esc(co.ogrn)], ["КПП", esc(co.kpp)], ["ОКПО", esc(co.okpo)],
        ["Основной ОКВЭД", co.okved_main ? `${esc(co.okved_main)} <span class="muted">${esc(App.data.okved[co.okved_main] || "")}</span>` : ""], ["Дата регистрации", esc(co.reg_date)],
        ["Юридический адрес", esc(co.address)], ["Почтовый адрес", esc(co.postal_address)], ["Сайт", esc(co.site)], ["Телефон", co.phone ? phoneHtml(co.phone) : ""], ["E-mail", esc(co.email)]])}</div>
      <div><div class="label" style="margin-bottom:6px">Представитель</div>${kv([["ФИО", esc(acc.fio)], ["Должность", esc(acc.position)], ["Рабочий e-mail", esc(acc.email)], ["Телефон", acc.phone ? phoneHtml(acc.phone) : ""]])}
        <p class="muted">Попросите подтверждение полномочий: доверенность или письмо на бланке компании. Позвоните по официальному телефону компании, а не только по указанному в заявке.</p></div>
    </div>
    <div class="form" style="margin-top:12px"><div class="field full"><label for="${rcId(id)}">Комментарий для пользователя</label>
      <input class="inp" id="${rcId(id)}" data-rc="${esc(id)}" value="${esc((UI.regComment || {})[id] || "")}" placeholder="Обязателен при отклонении: что исправить или какие документы прислать"></div>
      <div class="full row"><button class="btn pri" data-act="reg-approve" data-id="${esc(id)}">Подтвердить компанию и права представителя</button><button class="btn danger" data-act="reg-reject" data-id="${esc(id)}">Отклонить</button></div></div>
  </article>`;
}
function adminModeration() {
  const regs = App.registrations.slice().sort((a, b) => (b.submitted_at || "").localeCompare(a.submitted_at || ""));
  const pending = regs.filter((r) => !decisionFor(r)), done = regs.filter((r) => decisionFor(r));
  return `<section><h3 class="h3" style="margin-bottom:8px">Регистрации представителей: ожидают проверки (${pending.length})</h3>
    <p class="muted" style="margin-top:0;max-width:820px">Сверьте реквизиты с выпиской ЕГРЮЛ и убедитесь, что человек представляет компанию. После решения пользователь получит уведомление на сайте и копию в Telegram или ВКонтакте, если включил их в настройках. Подтверждённый представитель размещает предложения с пометкой «Представитель компании подтверждён».</p>
    ${pending.map(regCard).join("") || '<div class="note">Новых регистраций нет.</div>'}
    ${done.length ? `<h3 class="h3" style="margin:24px 0 8px">Рассмотренные (${done.length})</h3><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Компания</th><th>Представитель</th><th>Решение</th><th>Комментарий</th><th>Дата решения</th><th></th></tr></thead><tbody>
      ${done.map((r) => { const d = decisionFor(r); return `<tr><td>${r.base_id && App.C[r.base_id] ? `<a href="#c.${esc(r.base_id)}">${esc(r.company?.name)}</a>` : esc(r.company?.name)}<div class="muted">ИНН ${esc(r.company?.inn)}</div></td><td>${esc(r.account?.fio)}<div class="muted">${esc(r.account?.position)}</div></td>
        <td><span class="v ${d.status === "APPROVED" ? "yes" : "no"}">${d.status === "APPROVED" ? "Подтверждено" : "Отклонено"}</span></td><td>${esc(d.comment || "—")}</td><td>${fmtDate(d.decided_at)}</td>
        <td><button class="btn sm txt" data-act="${d.status === "APPROVED" ? "reg-revoke" : "reg-approve"}" data-id="${esc(r.id)}">${d.status === "APPROVED" ? "Отозвать подтверждение" : "Подтвердить"}</button></td></tr>`; }).join("")}
    </tbody></table></div>` : ""}</section>
  ${itemsModeration()}`;
}
// Решение модератора: запись в moderation (её видит пользователь), отметка подтверждённого представителя в reps, журнал
async function moderateRegistration(uid, status, comment) {
  const reg = App.registrations.find((x) => x.id === uid); if (!reg) return;
  if (status === "REJECTED" && !comment) { toast("Укажите причину: пользователь увидит её в уведомлении."); document.getElementById(rcId(uid))?.focus(); return; }
  const name = reg.company?.name || "компания";
  if (!(await Store.put("moderation", uid, { status, comment, decided_at: nowIso(), submitted_at: reg.submitted_at, moderator: App.uid, company_name: name }))) return;
  if (status === "APPROVED" && reg.base_id) await Store.put("reps", uid, { company_id: reg.base_id, company_name: name, approved_at: nowIso() });
  else await Store.del("reps", uid);
  if (UI.regComment) delete UI.regComment[uid];
  audit(`Регистрация представителя «${name}» (${reg.account?.fio || "ФИО не указано"}): ${status === "APPROVED" ? "подтверждена" : "отклонена"}${comment ? `. Комментарий: ${comment}` : ""}`);
  toast(status === "APPROVED" ? "Регистрация подтверждена. Пользователь получит уведомление." : "Регистрация отклонена. Пользователь получит уведомление с причиной.");
}
// id поля комментария модератора: в ключах бывают двоеточия и символы, недопустимые в селекторе
const rcId = (key) => "rc-" + String(key).replace(/[^\w-]/g, "_");
// Статус модерации записи простыми словами (для карточки предложения)
function modStatusTxt(coll, x) {
  const d = itemDecision(coll, x);
  if (!d) return "Ожидает проверки";
  return (d.status === "APPROVED" ? "Проверено модератором" : "Отклонено модератором") + (d.decided_at && !d.legacy ? ` ${fmtDate(d.decided_at)}` : "") + (d.comment ? `. ${esc(d.comment)}` : "");
}
// Предложения и заявки на проверке: карточки с сутью записи и решением; рассмотренные — отдельной таблицей
function itemsModeration() {
  const items = [...App.offers.map((x) => ({ coll: "offers", x })), ...App.requests.map((x) => ({ coll: "requests", x }))]
    .sort((a, b) => (b.x.created_at || "").localeCompare(a.x.created_at || ""));
  const pending = items.filter((i) => !itemDecision(i.coll, i.x)), done = items.filter((i) => itemDecision(i.coll, i.x));
  const title = (i) => (i.coll === "offers" ? i.x.title : i.x.what);
  // предложение открывается панелью, заявка — страницей; выглядят одинаково, как ссылки
  const open = (i) => (i.coll === "offers" ? `<button class="lnk" data-act="offer-open" data-id="${esc(i.x.id)}">${esc(title(i))}</button>` : `<a href="#r.${esc(i.x.id)}">${esc(title(i))}</a>`);
  return `<section class="sec"><h3 class="h3" style="margin-bottom:8px">Предложения и заявки: ожидают проверки (${pending.length})</h3>
    <p class="muted" style="margin-top:0;max-width:820px">Записи видны на сайте сразу после публикации с пометкой «Указано пользователем». Одобренные получают пометку «Проверено модератором», отклонённые скрываются из общих списков. Автор получает уведомление с решением.</p>
    ${pending.map(itemCard).join("") || '<div class="note">Новых предложений и заявок нет.</div>'}
    ${done.length ? `<h3 class="h3" style="margin:24px 0 8px">Рассмотренные (${done.length})</h3><div class="tbl-wrap"><table class="tbl"><thead><tr><th>Тип</th><th>Название</th><th>Решение</th><th>Комментарий</th><th>Дата решения</th><th></th></tr></thead><tbody>
      ${done.map((i) => { const d = itemDecision(i.coll, i.x); return `<tr><td>${i.coll === "offers" ? "Предложение" : "Заявка"}</td><td>${open(i)}</td>
        <td><span class="v ${d.status === "APPROVED" ? "yes" : "no"}">${d.status === "APPROVED" ? "Одобрено" : "Отклонено"}</span></td><td>${esc(d.comment || "—")}</td><td>${d.legacy ? unk("na") : fmtDate(d.decided_at)}</td>
        <td><button class="btn sm txt" data-act="item-reopen" data-key="${esc(i.coll + ":" + i.x.id)}">Вернуть на проверку</button></td></tr>`; }).join("")}
    </tbody></table></div>` : ""}</section>`;
}
function itemCard({ coll, x }) {
  const key = coll + ":" + x.id, offer = coll === "offers";
  const co = App.C[offer ? x.company_id : x.target_company];
  const qty = x.qty ? `${x.qty} ${x.unit || ""}${x.period ? " в " + (x.period === "мес" ? "месяц" : "год") : ""}` : "";
  const facts = offer
    ? [["Категория", esc(x.kind_label)], ["Предприятие", co ? `<a href="#c.${esc(co.id)}">${esc(x.company_name)}</a>` : esc(x.company_name)], ["Цена", x.price ? priceHtml(x.price) : ""],
       ["Количество", esc(qty)], ["ОКПД2", esc(x.okpd2)], ["Город отгрузки", esc(x.city)], ["Описание", esc(x.description)], ["Характеристики", esc(x.specs).replace(/\n/g, "<br>")]]
    : [["Количество", esc(qty)], ["Материал", esc(x.material)], ["ОКПД2", esc(x.okpd2)], ["Характеристики", esc(x.specs)], ["Регион, город", esc([x.region_name, x.city].filter(Boolean).join(", "))],
       ["Бюджет", x.budget ? esc(Number(x.budget).toLocaleString("ru-RU")) + " ₽" : ""], ["Срок", x.deadline ? fmtDate(x.deadline) : ""],
       ["Адресат", co ? `<a href="#c.${esc(co.id)}">${esc(co.name)}</a>` : ""], ["Доп. требования", esc(x.extra)]];
  const author = offer && isVerifiedRep(x.author, x.company_id) ? '<span class="v yes">Представитель компании подтверждён</span>' : '<span class="v part">Автор не подтверждён как представитель</span>';
  return `<article class="card" style="margin-bottom:12px">
    <div class="card-head"><div style="min-width:0"><span class="label">${offer ? "Предложение о продаже" : "Заявка на покупку"} · ${fmtDate(x.created_at)}</span>
      <h3 class="h3">${esc(offer ? x.title : x.what)}</h3><div style="margin-top:4px">${author}</div></div>
      ${offer ? `<button class="btn sm" data-act="offer-open" data-id="${esc(x.id)}">Открыть</button>` : `<a class="btn sm" href="#r.${esc(x.id)}">Открыть</a>`}</div>
    <dl class="kv" style="margin-top:12px">${facts.filter(([, v]) => v).map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("") || `<dt>Подробности</dt><dd>${unk("na")}</dd>`}</dl>
    <div class="form" style="margin-top:12px"><div class="field full"><label for="${rcId(key)}">Комментарий для автора</label>
      <input class="inp" id="${rcId(key)}" data-rc="${esc(key)}" value="${esc((UI.regComment || {})[key] || "")}" placeholder="Обязателен при отклонении: что не так и как исправить"></div>
      <div class="full row"><button class="btn pri" data-act="item-approve" data-key="${esc(key)}">Одобрить</button><button class="btn danger" data-act="item-reject" data-key="${esc(key)}">Отклонить</button></div></div>
  </article>`;
}
// Решение модератора по предложению или заявке; автор получит уведомление при следующем обновлении данных
async function moderateItem(key, status, comment) {
  const i = key.indexOf(":"), coll = key.slice(0, i), id = key.slice(i + 1);
  const x = (App[coll] || []).find((r) => r.id === id); if (!x) return;
  if (status === "REJECTED" && !comment) { toast("Укажите причину: автор увидит её в уведомлении."); document.getElementById(rcId(key))?.focus(); return; }
  if (!(await Store.put("decisions", key, { coll, item_id: id, status, comment, decided_at: nowIso(), moderator: App.uid }))) return;
  if (UI.regComment) delete UI.regComment[key];
  const what = coll === "offers" ? `Предложение «${x.title}»` : `Заявка «${x.what}»`, ok = status === "APPROVED";
  audit(`${what}: ${ok ? (coll === "offers" ? "одобрено" : "одобрена") : (coll === "offers" ? "отклонено" : "отклонена")} модератором${comment ? `. Комментарий: ${comment}` : ""}`);
  toast(`${what} ${ok ? (coll === "offers" ? "одобрено" : "одобрена") : (coll === "offers" ? "отклонено" : "отклонена")}. Автор получит уведомление.`);
}
// Вернуть запись на проверку: решение снимается, запись снова в очереди
async function reopenItem(key) {
  const i = key.indexOf(":"), coll = key.slice(0, i), id = key.slice(i + 1);
  const x = (App[coll] || []).find((r) => r.id === id); if (!x) return;
  await Store.del("decisions", key);
  if (["APPROVED", "REJECTED"].includes(x.status)) { const { id: _id, ...rest } = x; await Store.put(coll, id, { ...rest, status: "NEW" }); }
  toast("Запись возвращена на проверку.");
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
