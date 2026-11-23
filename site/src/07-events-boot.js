/* ===== События и запуск ===== */

/* ---------- Ручные изменения статусов модератором поверх базы ---------- */
// Статусы хранятся в коллекции overrides (документ на предприятие, писать может только модератор — правила доступа в README).
// Старые записи override в общей коллекции reports мог создать любой зритель, поэтому они учитываются только на этом устройстве
function applyOverrides() {
  for (const c of App.data.companies) {
    if (c._orig == null) c._orig = c.verification_status;
    c.verification_status = c._orig;
  }
  const legacy =
    App.mode === "local" ? (App.reports || []).filter((x) => x.kind === "override") : [];
  for (const r of [
    ...legacy,
    ...App.overrides.map((x) => ({ ...x, company_id: x.company_id || x.id })),
  ].sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""))) {
    if (App.C[r.company_id] && STATUS_LABEL[r.status])
      App.C[r.company_id].verification_status = r.status;
  }
}
const _render0 = render;
render = function () {
  if (App.data) {
    applyOverrides();
    applyProductEdits();
  }
  _render0();
};

/* ---------- Вспомогательные функции форм и журнал действий ---------- */
const formData = (f) => Object.fromEntries(new FormData(f).entries());
const audit = (text) =>
  Store.put("reports", "a-" + uidGen(), {
    kind: "audit",
    text,
    author: App.uid,
    created_at: nowIso(),
  });

document.addEventListener("submit", async (e) => {
  const f = e.target;
  e.preventDefault();
  if (f.id === "reg-form") {
    regNext();
    return;
  }
  const d = formData(f);
  if (f.matches("[data-finance-form]")) {
    const companyId = f.dataset.financeForm;
    if (App.mode !== "api" || !canEditProducts(companyId)) {
      toast("Отправить данные может только подтверждённый представитель компании.");
      return;
    }
    const activities = [...f.querySelectorAll("[data-finance-row]")].map((row) => ({
      okved_code: row.querySelector('[name="okved_code"]').value.trim() || null,
      activity_name: row.querySelector('[name="activity_name"]').value.trim(),
      revenue: Number(row.querySelector('[name="revenue"]').value),
      share:
        row.querySelector('[name="share"]').value === ""
          ? null
          : Number(row.querySelector('[name="share"]').value),
    }));
    try {
      const saved = await API.call(
        "POST",
        `/api/v1/companies/${encodeURIComponent(companyId)}/financial-submissions`,
        {
          report_year: Number(d.report_year),
          scope: d.scope,
          document_url: d.document_url.trim(),
          activities,
        }
      );
      UI.financeClaims[companyId] = [saved, ...(UI.financeClaims[companyId] || [])];
      UI.financeClaimsLoaded[companyId] = true;
      await refreshCatalog();
      render();
      toast("Структура выручки отправлена. В поиске она отмечена как заявленная предприятием.");
    } catch (err) {
      toast(err.message || "Не удалось отправить структуру выручки.");
    }
    return;
  }
  if (f.id === "login-form") {
    const email = (d.email || "").trim().toLowerCase();
    if (email && email === (App.profile.account?.email || "").trim().toLowerCase()) {
      Object.assign(UI, { loginErr: "", loginEmail: "", cabinetTab: "company" });
      App.profile.signedOut = false;
      await Store.saveProfile();
      render();
      toast("Вы вошли в личный кабинет.");
    } else {
      Object.assign(UI, {
        loginErr:
          App.mode === "api"
            ? "Аккаунт с таким e-mail в этом браузере не найден. Проверьте адрес или зарегистрируйтесь."
            : "Аккаунт с таким e-mail на этом устройстве не найден. Проверьте адрес или зарегистрируйтесь.",
        loginEmail: d.email || "",
      });
      render();
    }
    return;
  }
  if (f.id === "home-search" || f.id === "main-search") {
    if (d.q.trim()) runSearch(d.q.trim(), false);
    return;
  }
  if (f.id === "offer-form") {
    const co = App.data.companies.find((c) => c.name === d.company_name);
    const priceNum = d.price ? Number(String(d.price).replace(/\s/g, "").replace(",", ".")) : null;
    if (d.price && !(priceNum >= 0)) {
      toast("Цена: укажите число, например 125000");
      return;
    }
    const id = "o-" + uidGen();
    const ok = await Store.put("offers", id, {
      title: d.title,
      kind_label: d.kind_label,
      company_name: d.company_name,
      company_id: co?.id || null,
      description: d.description,
      material: d.material,
      okpd2: d.okpd2,
      specs: d.specs,
      qty: d.qty,
      unit: d.unit,
      // торг или окончательная цена — только если цена указана; у «Цены по запросу» пометки нет
      price: d.price
        ? {
            value: priceNum,
            currency: "₽",
            unit: d.price_unit || d.unit,
            date: TODAY,
            negotiable: d.negotiable === "on",
          }
        : null,
      country:
        String(d.country || "")
          .trim()
          .slice(0, 60) || null,
      min_batch: d.min_batch,
      lead_prod: d.lead_prod,
      lead_deliv: d.lead_deliv,
      city: d.city,
      warehouse: d.warehouse,
      terms: d.terms,
      docs: d.docs,
      author: App.uid,
      status: "NEW",
      created_at: nowIso(),
    });
    if (ok) {
      closePanel();
      toast("Предложение опубликовано и ожидает модерации.");
      location.hash = "#sell";
    }
    return;
  }
  if (f.id === "request-form") {
    const id = "r-" + uidGen();
    const ok = await Store.put("requests", id, {
      ...d,
      region_name: d.region ? regionName(d.region) : "Любой",
      author: App.uid,
      status: "NEW",
      created_at: nowIso(),
      company_id: null,
    });
    if (ok) {
      closePanel();
      toast(
        d.target_company
          ? "Запрос отправлен."
          : "Заявка создана. Показаны потенциальные поставщики."
      );
      location.hash = "#r." + id;
    }
    return;
  }
  if (f.id === "respond-form") {
    const r = App.requests.find((x) => x.id === f.dataset.id);
    if (!r) return;
    // отдельная запись: документ заявки остаётся за автором, параллельные отклики не затирают друг друга
    if (
      await Store.put("responses", "resp-" + uidGen(), {
        request_id: r.id,
        company: d.company,
        text: d.text,
        price: d.price || null,
        author: App.uid,
        at: nowIso(),
      })
    ) {
      f.reset();
      toast("Отклик отправлен.");
    }
    return;
  }
  if (f.id === "claim-form") {
    if (!App.profile.companies.some((x) => x.company_id === d.company_id))
      App.profile.companies.push({
        company_id: d.company_id,
        role: d.role,
        status: "Ожидает подтверждения модератором",
      });
    await Store.saveProfile();
    rerender();
    toast("Запрос на привязку отправлен.");
    return;
  }
  if (f.id === "wh-form") {
    App.profile.warehouses.push({ id: uidGen(), ...d });
    await Store.saveProfile();
    rerender();
    toast("Склад добавлен.");
    return;
  }
  if (f.id === "settings-form") {
    App.profile.city = d.city;
    await Store.saveProfile();
    rerender();
    toast("Настройки сохранены.");
    return;
  }
  if (f.id === "product-edit-form") {
    const pid = f.dataset.product,
      cur = App.P[pid];
    if (!cur || !canEditProducts(cur.company_id)) {
      toast("Изменять позицию может только подтверждённый представитель компании.");
      return;
    }
    const fields = productFields(d);
    if (fields.name.length < 2) {
      toast("Укажите название позиции.");
      return;
    }
    if (await saveProductEdit(pid, { deleted: false, fields })) {
      closePanel();
      toast("Позиция сохранена.");
      audit(
        `Представитель «${App.C[cur.company_id]?.short || ""}» изменил позицию «${fields.name}»`
      );
    }
    return;
  }
  if (f.id === "report-form") {
    await Store.put("reports", "d-" + uidGen(), {
      kind: "data_error",
      company_id: f.dataset.company,
      field: d.field,
      text: d.text,
      author: App.uid,
      created_at: nowIso(),
    });
    closePanel();
    toast("Сообщение передано модератору.");
    return;
  }
});

/* ---------- Клики: кнопки действий, избранное, сравнение, вкладки ---------- */
document.addEventListener("click", async (e) => {
  const t = e.target.closest("button,[data-act]");
  if (!t) return;
  if (t.dataset.regPick) {
    regPick(t.dataset.regPick);
    return;
  }
  if (t.dataset.regPickName) {
    regPick(null, t.dataset.regPickName);
    return;
  }
  if (t.dataset.example) {
    runSearch(t.dataset.example, false);
    return;
  }
  if (t.dataset.fav) {
    toggleList("favorites", t.dataset.fav);
    return;
  }
  if (t.dataset.cmp) {
    toggleList("compare", t.dataset.cmp);
    return;
  }
  if (t.dataset.cmptab) {
    UI.cmpTab = t.dataset.cmptab;
    render();
    return;
  }
  if (t.dataset.page) {
    const [k, n] = t.dataset.page.split(":");
    UI[k].page = Number(n);
    render();
    window.scrollTo(0, 0);
    return;
  }
  if (t.dataset.ctab) {
    location.hash = "#cabinet." + t.dataset.ctab;
    return;
  }
  if (t.dataset.atab) {
    location.hash = "#admin." + t.dataset.atab;
    return;
  }
  if (t.dataset.sellf != null) {
    UI.sellFilter = t.dataset.sellf;
    UI.sell.page = 1;
    render();
    return;
  }
  if (t.dataset.financeAdd) {
    const form = document.querySelector(
      `[data-finance-form="${CSS.escape(t.dataset.financeAdd)}"]`
    );
    form
      ?.querySelector("[data-finance-rows]")
      ?.insertAdjacentHTML("beforeend", financeActivityRow(t.dataset.financeAdd));
    return;
  }
  if (t.hasAttribute("data-finance-remove")) {
    const rows = t.closest("form")?.querySelectorAll("[data-finance-row]") || [];
    if (rows.length > 2) t.closest("[data-finance-row]")?.remove();
    else toast("Оставьте не менее двух направлений.");
    return;
  }
  if (t.dataset.finReview) {
    await reviewFinancialSubmission(t.dataset.finReview, t.dataset.status);
    return;
  }
  const a = t.dataset.act;
  if (!a) return;
  if (a === "catalog-retry") {
    showCatalogLoading("Повторно проверяем каталог", "Обновляем данные и проверяем их актуальность.");
    await new Promise((resolve) => requestAnimationFrame(resolve));
    await boot();
    return;
  }
  // Регистрация: навигация по шагам
  if (a === "reg-back") {
    UI.reg.errors = {};
    UI.reg.step--;
    render();
    window.scrollTo(0, 0);
    return;
  }
  if (a === "reg-clear") {
    Object.assign(UI.reg, { co: {}, from: null, fromKeys: [], checked: false, errors: {} });
    render();
    return;
  }
  if (a === "reg-finish") {
    await regSave();
    return;
  }
  if (a === "reg-edit") {
    const p = App.profile;
    UI.reg = {
      ...newReg(),
      step: 2,
      edit: true,
      acc: { ...p.account },
      co: { ...p.company },
      fromKeys: p.company?.from_base || [],
      from: p.company?.base_id
        ? {
            id: p.company.base_id,
            name: App.C[p.company.base_id]?.name,
            egr: egrulSrc(App.C[p.company.base_id]),
          }
        : null,
    };
    render();
    window.scrollTo(0, 0);
    return;
  }
  if (a === "reg-cancel") {
    UI.reg = null;
    render();
    return;
  }
  // Выход из кабинета и регистрация другой компании с экрана входа
  if (a === "logout") {
    App.profile.signedOut = true;
    UI.reg = null;
    UI.loginErr = "";
    await Store.saveProfile();
    closePanel();
    location.hash = "#home";
    render();
    toast("Вы вышли из личного кабинета.");
    return;
  }
  if (a === "reg-new") {
    UI.reg = { ...newReg(), fresh: true };
    UI.loginErr = "";
    render();
    window.scrollTo(0, 0);
    return;
  }
  // Модерация регистраций представителей
  if (a === "reg-approve" || a === "reg-reject") {
    await moderateRegistration(
      t.dataset.id,
      a === "reg-approve" ? "APPROVED" : "REJECTED",
      ((UI.regComment || {})[t.dataset.id] || "").trim()
    );
    return;
  }
  // Модерация предложений и заявок
  if (a === "item-approve" || a === "item-reject") {
    await moderateItem(
      t.dataset.key,
      a === "item-approve" ? "APPROVED" : "REJECTED",
      ((UI.regComment || {})[t.dataset.key] || "").trim()
    );
    return;
  }
  if (a === "item-reopen") {
    await reopenItem(t.dataset.key);
    return;
  }
  if (a === "reg-revoke") {
    await moderateRegistration(t.dataset.id, "REJECTED", "Подтверждение отозвано модератором");
    return;
  }
  // Админ-панель, «Предприятия»: раскрыть все данные, сбросить фильтры
  // Сбор данных: ручной запуск и обновление состояния
  if (a === "sync-run") {
    await startSync();
    return;
  }
  if (a === "sync-refresh") {
    await refreshSync();
    return;
  }
  if (a === "sites-refresh") {
    await loadSites();
    return;
  }
  if (a === "site-ok" || a === "site-no") {
    await decideSite(
      t.dataset.company,
      t.dataset.domain,
      a === "site-ok" ? "CONFIRMED" : "REJECTED"
    );
    return;
  }
  if (a === "adm-open") {
    UI.adm.open = UI.adm.open === t.dataset.id ? null : t.dataset.id;
    render();
    return;
  }
  if (a === "adm-reset") {
    Object.assign(UI.adm, { q: "", region: "", st: "", origin: "", page: 1, open: null });
    render();
    return;
  }
  // Уведомления на сайте: прочитано, все прочитаны, открыть (ссылка откроется сама)
  if (a === "notice-read" || a === "notice-open") {
    const x = (App.profile.inbox || []).find((n) => n.id === t.dataset.id);
    if (x) {
      x.read = true;
      await Store.saveProfile();
      if (a === "notice-read") render();
    }
    return;
  }
  if (a === "notice-read-all") {
    (App.profile.inbox || []).forEach((n) => (n.read = true));
    await Store.saveProfile();
    render();
    return;
  }
  switch (a) {
    case "finance-queue-refresh":
      UI.financialQueue = null;
      UI.financialQueueError = null;
      await loadFinancialQueue();
      break;
    case "products-all":
      UI.allProducts = t.dataset.company;
      render();
      break;
    case "filters-open":
      $("#filters")?.classList.add("open");
      break;
    case "cat-scope":
      UI.companies.scope = t.dataset.scope;
      render();
      break;
    case "filters-close":
      $("#filters")?.classList.remove("open");
      break;
    case "reset-companies":
      UI.companies.f = {};
      UI.companies.q = "";
      UI.companies.page = 1;
      render();
      break;
    case "reset-sf":
      UI.sf = {
        hide: [],
        cities: [],
        noRisk: false,
        site: false,
        category: "",
        subcategory: "",
        kind: "",
        material: "",
        volume: "",
        scale: "",
        mainOkved: "",
        revenueOkved: "",
        financialYear: "",
        confirmedFinance: false,
      };
      render();
      break;
    case "reset-products":
      UI.products.f = {};
      UI.products.q = "";
      UI.products.page = 1;
      render();
      break;
    case "ai-parse": {
      const v = $("#sq")?.value.trim();
      if (v) runSearch(v, true);
      else toast("Введите запрос.");
      break;
    }
    case "save-search":
      if (UI.lastQuery) {
        App.profile.saved.unshift({ text: UI.lastQuery.raw, at: nowIso() });
        await Store.saveProfile();
        toast("Поиск сохранён в личном кабинете.");
      }
      break;
    case "saved-run":
      runSearch(App.profile.saved[Number(t.dataset.i)].text, false);
      break;
    case "saved-del":
      App.profile.saved.splice(Number(t.dataset.i), 1);
      await Store.saveProfile();
      rerender();
      break;
    case "compare-results":
      UI.lastResults.slice(0, 4).forEach((m) => {
        if (!App.profile.compare.includes("c:" + m.c.id)) App.profile.compare.push("c:" + m.c.id);
      });
      App.profile.compare = App.profile.compare.slice(-4);
      await Store.saveProfile();
      location.hash = "#compare";
      break;
    case "compare-clear":
      App.profile.compare = [];
      await Store.saveProfile();
      rerender();
      break;
    // своя продукция и свои записи: запрашивать предложение у себя нельзя
    case "prod-edit":
      openProductEdit(t.dataset.product);
      break;
    case "prod-del":
      confirmProductDelete(t.dataset.product);
      break;
    case "prod-del-confirm": {
      const cur = App.P[t.dataset.product];
      if (!cur || !canEditProducts(cur.company_id)) break;
      if (await saveProductEdit(cur.id, { deleted: true })) {
        closePanel();
        toast("Позиция удалена. Вернуть её можно во вкладке «Мои предложения».");
        audit(`Представитель «${App.C[cur.company_id]?.short || ""}» удалил позицию «${cur.name}»`);
        if (location.hash === "#p." + cur.id) location.hash = "#cabinet.offers";
      }
      break;
    }
    case "prod-restore": {
      const c = App.data.companies.find((x) =>
        (x._deleted || []).some((q) => q.id === t.dataset.product)
      );
      if (!c || !canEditProducts(c.id)) break;
      if (await saveProductEdit(t.dataset.product, { deleted: false }))
        toast("Позиция возвращена в каталог.");
      break;
    }
    case "rfq": {
      const p = t.dataset.product ? App.P[t.dataset.product] : null;
      const cid = t.dataset.company || p?.company_id;
      if (isMine(cid)) {
        toast("Это ваша компания: запрашивать предложение у себя не нужно.");
        break;
      }
      openRequestForm({
        target_company: cid,
        target_product: p?.id || "",
        what: p ? p.name : "",
        okpd2: p?.okpd2?.code || "",
      });
      break;
    }
    case "rfq-offer": {
      const own = App.offers.find((x) => x.id === t.dataset.id);
      if (own && isMine(own.company_id, own.author)) {
        toast("Это ваше предложение: запрашивать его у себя не нужно.");
        break;
      }
      const o = App.offers.find((x) => x.id === t.dataset.id);
      openRequestForm({
        target_company: o?.company_id || "",
        what: o?.title || "",
        okpd2: o?.okpd2 || "",
        unit: o?.unit,
      });
      break;
    }
    case "to-request": {
      const p = App.P[t.dataset.product];
      if (!p || isMine(p.company_id)) break;
      openRequestForm({ what: p.name, okpd2: p.okpd2?.code || "" });
      break;
    }
    case "offer-new":
      openOfferForm();
      break;
    case "offer-open":
      offerDetails(t.dataset.id);
      break;
    case "offer-del":
      await Store.del("offers", t.dataset.id);
      closePanel();
      toast("Предложение снято с публикации.");
      break;
    case "request-new":
      openRequestForm();
      break;
    case "request-del":
      await Store.del("requests", t.dataset.id);
      location.hash = "#buy";
      toast("Заявка закрыта.");
      break;
    case "report":
      openPanel(
        `<div class="panel-h"><div><div class="label">Сообщить об ошибке</div><h2 class="h2">${esc(App.C[t.dataset.company].short)}</h2></div><button class="x" data-close aria-label="Закрыть">×</button></div>
      <form id="report-form" class="form" data-company="${esc(t.dataset.company)}"><div class="field full"><label for="rp-f">Поле</label><input class="inp" id="rp-f" name="field" placeholder="например: адрес"></div><div class="field full"><label for="rp-t">Что неверно и где подтверждение *</label><textarea class="inp" id="rp-t" name="text" required></textarea></div><div class="full"><button class="btn pri" type="submit">Отправить</button></div></form>`,
        "narrow"
      );
      break;
    case "report-close":
      await Store.del("reports", t.dataset.id);
      break;
    case "recrawl":
      await queueRecrawl(t.dataset.url);
      break;
    case "unclaim":
      App.profile.companies = App.profile.companies.filter((x) => x.company_id !== t.dataset.id);
      await Store.saveProfile();
      rerender();
      break;
    case "wh-del":
      App.profile.warehouses = App.profile.warehouses.filter((x) => x.id !== t.dataset.id);
      await Store.saveProfile();
      rerender();
      break;
    case "menu":
      $("#drawer").classList.toggle("open");
      break;
  }
});

/* ---------- Изменения полей: фильтры, сортировка, переключатели ---------- */
document.addEventListener("change", async (e) => {
  const t = e.target;
  // Регистрация: галочки согласия и проверки данных
  if (t.dataset.rchk) {
    UI.reg[t.dataset.rchk] = t.checked;
    delete UI.reg.errors[t.dataset.rchk];
    t.closest(".has-err")?.classList.remove("has-err");
    return;
  }
  // Уведомления: канал вкл/выкл, контакт, события
  if (t.dataset.nch || t.dataset.ncontact || t.dataset.nev) {
    const n = App.profile.notify || (App.profile.notify = defaultNotify());
    if (t.dataset.nch) {
      n.channels[t.dataset.nch].on = t.checked;
      toast(
        (t.checked ? "Включены" : "Выключены") +
          " уведомления: " +
          (t.dataset.nch === "vk" ? "ВКонтакте" : "Telegram")
      );
    }
    if (t.dataset.ncontact) {
      const v = notifyContact(t.dataset.ncontact, t.value);
      if (v === null) {
        toast("Не удалось распознать контакт. Проверьте формат.");
        return;
      }
      n.channels[t.dataset.ncontact].contact = v;
      toast("Контакт сохранён");
    }
    if (t.dataset.nev) {
      const [ev, ch] = t.dataset.nev.split(":");
      n.events[ev][ch] = t.checked;
    }
    await Store.saveProfile();
    render();
    return;
  }
  if (t.dataset.sellcountry) {
    UI.sell.country = t.value;
    UI.sell.page = 1;
    render();
    return;
  }
  if (t.id === "cmp-diff") {
    UI.cmpDiff = t.checked;
    render();
    return;
  }
  if (t.id === "show-unv") {
    App.showUnverified = t.checked;
    if (UI.lastQuery)
      UI.lastResults = searchCompanies(UI.lastQuery, { includeUnverified: App.showUnverified });
    UI.companies.page = UI.products.page = 1;
    render();
    return;
  }
  if (t.dataset.f) {
    const [k, f] = t.dataset.f.split(":");
    UI[k].f[f] = t.value;
    UI[k].page = 1;
    render();
    return;
  }
  if (t.dataset.fs) {
    const h = UI.companies.f.hide || (UI.companies.f.hide = []);
    if (t.checked) UI.companies.f.hide = h.filter((x) => x !== t.dataset.fs);
    else h.push(t.dataset.fs);
    UI.companies.page = 1;
    render();
    return;
  }
  if (t.dataset.fb) {
    UI.companies.f[t.dataset.fb] = t.checked;
    UI.companies.page = 1;
    render();
    return;
  }
  if (t.dataset.sfHide) {
    const k = t.dataset.sfHide;
    UI.sf.hide = t.checked ? UI.sf.hide.filter((x) => x !== k) : [...UI.sf.hide, k];
    render();
    return;
  }
  if (t.dataset.sfCity) {
    const k = t.dataset.sfCity;
    UI.sf.cities = t.checked ? UI.sf.cities.filter((x) => x !== k) : [...UI.sf.cities, k];
    render();
    return;
  }
  if (t.dataset.sfSelect) {
    UI.sf[t.dataset.sfSelect] = t.value;
    render();
    return;
  }
  if (t.dataset.sf) {
    UI.sf[t.dataset.sf] = t.checked;
    render();
    return;
  }
  if (t.dataset.fb2) {
    UI.products.f[t.dataset.fb2] = t.checked;
    UI.products.page = 1;
    render();
    return;
  }
  if (t.dataset.sort) {
    if (t.dataset.sort === "search") UI.searchSort = t.value;
    else {
      UI[t.dataset.sort].sort = t.value;
      UI[t.dataset.sort].page = 1;
    }
    render();
    return;
  }
  if (t.dataset.srcflag) {
    await Store.put("sourceflags", t.dataset.srcflag, { disabled: !t.checked, at: nowIso() });
    audit(
      `Источник ${App.S[t.dataset.srcflag].source_title} (${App.C[App.S[t.dataset.srcflag].company_id].short}) ${t.checked ? "включён" : "отключён"}`
    );
    return;
  }
  if (t.dataset.setstatus) {
    const c = App.C[t.dataset.setstatus],
      was = c.verification_status;
    if (
      await Store.put("overrides", c.id, {
        company_id: c.id,
        status: t.value,
        author: App.uid,
        created_at: nowIso(),
      })
    ) {
      audit(
        `Статус проверки «${c.short || c.name}»: ${STATUS_LABEL[was]} → ${STATUS_LABEL[t.value]}`
      );
      toast(`«${c.short || c.name}»: ${STATUS_LABEL[t.value].toLowerCase()}`);
    }
    return;
  }
  // токен модератора: в режиме сервера меняется пользователь, от имени которого работает сайт
  if (t.dataset.apitoken) {
    LS.set("apitoken", t.value.trim());
    if (App.mode === "api") {
      await Store.init();
      render();
      if (!App.canEdit && t.value.trim()) toast("Токен не подошёл.");
    }
    refreshSync();
    return;
  }
  if (t.dataset.adm) {
    UI.adm[t.dataset.adm] = t.value;
    UI.adm.page = 1;
    UI.adm.open = null;
    render();
    return;
  }
});

/* ---------- Живой поиск по каталогам с задержкой ввода ---------- */
let _qt = 0;
document.addEventListener("input", (e) => {
  const t = e.target;
  // Регистрация: ввод полей без перерисовки и подсказки по названию компании
  if (t.dataset.rf) {
    const [sc, k] = t.dataset.rf.split(".");
    UI.reg[sc][k] = t.value;
    return;
  }
  if (t.dataset.rq) {
    const ul = $("#rg-sugg");
    if (ul) ul.innerHTML = regSuggestHtml(regSuggest(t.value));
    return;
  }
  // Комментарий модератора к регистрации: хранится между перерисовками, пока не принято решение
  // галочка «Возможен торг» доступна, только когда указана цена
  if (t.id === "of-price") {
    const cb = document.getElementById("of-neg");
    if (cb) {
      cb.disabled = !t.value.trim();
      if (cb.disabled) cb.checked = false;
    }
    const hint = document.getElementById("of-neg-hint");
    if (hint) hint.hidden = !!t.value.trim();
    return;
  }
  if (t.dataset.rc) {
    (UI.regComment || (UI.regComment = {}))[t.dataset.rc] = t.value;
    return;
  }
  if (t.dataset.adm === "q") {
    clearTimeout(_qt);
    _qt = setTimeout(() => {
      UI.adm.q = t.value;
      UI.adm.page = 1;
      render();
    }, 250);
    return;
  }
  if (!t.dataset.q) return;
  clearTimeout(_qt);
  _qt = setTimeout(() => {
    UI[t.dataset.q].q = t.value;
    UI[t.dataset.q].page = 1;
    render();
  }, 250);
});

/* ---------- Запуск: загрузка каталога и первая отрисовка ---------- */
// Каталог отдаёт сервер платформы из PostgreSQL: облегчённые карточки, сжатые gzip; пока база не менялась,
// браузер получает ответ 304 и берёт каталог из своего кеша. data.json — только для просмотра сайта без сервера
/**
 * Загружает каталог с API, используя локальный файл только при недоступности API.
 * @returns {Promise<object>} Пакет каталога.
 * @throws {Error} Если ни один источник каталога не ответил успешно.
 */
/** Запускает начальную загрузку данных, подписки и первой страницы приложения. */
async function boot() {
  showCatalogLoading();
  try {
    await refreshCatalog();
  } catch (e) {
    if (route().name === "stats") {
      render();
      return;
    }
    $("#app").innerHTML =
      `<div class="wrap page"><div class="catalog-state"><div class="note warn" role="alert">${esc(catalogLoadMessage(e))}</div><button class="btn" data-act="catalog-retry">Повторить загрузку</button></div></div>`;
    return;
  }
  render();
  await Store.init();
  // избранное и сравнение могут ссылаться на предприятия не из каталога браузера (список «Все предприятия РФ»)
  for (const k of [...(App.profile.favorites || []), ...(App.profile.compare || [])]) {
    const [tp, id] = k.split(":");
    if (tp === "c" && !App.C[id]) loadCompany(id);
  }
  await ensureRegistrationSubmitted();
  render();
  openFromHash();
}

function catalogLoadingMarkup(title = "Загружаем каталог", description = "Получаем свежие данные и подготавливаем их к показу.") {
  return `<div class="catalog-loading" role="status" aria-live="polite"><span class="catalog-loader" aria-hidden="true"><i></i></span><div class="catalog-loading__copy"><b>${esc(title)}</b><span>${esc(description)}</span><span class="catalog-loading__track" aria-hidden="true"><i></i></span></div></div>`;
}

function showCatalogLoading(title, description) {
  const app = $("#app");
  if (app) app.innerHTML = `<div class="wrap page">${catalogLoadingMarkup(title, description)}</div>`;
}

let _catalogExpiryTimer = 0;
let _catalogLastCheck = 0;

async function refreshCatalog() {
  const previousETag = App.catalogEtag;
  const loaded = await loadCatalogSnapshot(fetch, App.catalogEtag, App.data);
  if (isCatalogRollback(loaded.data, App.data, loaded.etag, App.catalogEtag)) {
    throw Object.assign(new Error("Версия каталога уменьшилась."), { code: "CATALOG_ROLLBACK" });
  }
  const savedVersion = LS.get("catalog_version", null);
  if (isCatalogRollback(loaded.data, savedVersion, loaded.etag, savedVersion?.etag)) {
    throw Object.assign(new Error("Версия каталога ниже ранее принятой."), { code: "CATALOG_ROLLBACK" });
  }
  App.catalogSource = loaded.source;
  App.catalogSyncAt = loaded.freshness.sourceUpdatedAt;
  App.catalogEtag = loaded.etag || null;
  if (!loaded.unchanged) {
    const previousRevision = App.data?.revision;
    indexData(loaded.data);
    if (
      previousRevision != null &&
      (previousRevision !== loaded.data.revision || previousETag !== loaded.etag) &&
      UI.lastQuery
    ) {
      UI.lastResults = searchCompanies(UI.lastQuery, { includeUnverified: App.showUnverified });
    }
  }
  if (loaded.source === "api") {
    LS.set("catalog_version", {
      revision: loaded.data.revision,
      sync: { finished: loaded.freshness.sourceUpdatedAt },
      etag: loaded.etag,
    });
  }
  _catalogLastCheck = Date.now();
  clearTimeout(_catalogExpiryTimer);
  _catalogExpiryTimer = setTimeout(
    () => revalidateCatalog(true),
    Math.max(0, CATALOG_MAX_AGE_MS - loaded.freshness.ageMs + 1)
  );
  return loaded.data;
}

function invalidateStaleCatalog(error) {
  clearCatalogLoadCaches();
  App.data = null;
  App.catalogEtag = null;
  App.C = {};
  App.P = {};
  App.S = {};
  const message = catalogLoadMessage(error);
  if (route().name === "stats") {
    render();
    return;
  }
  $("#app").innerHTML = `<div class="wrap page"><div class="note warn" role="alert">${esc(message)}</div></div>`;
}

async function revalidateCatalog(force = false) {
  if (!App.catalogSyncAt) return;
  const freshness = inspectCatalogFreshness(App.catalogSyncAt);
  if (!force && document.visibilityState !== "visible") return;
  if (!force && Date.now() - _catalogLastCheck < 30 * 1000) return;
  if (!force && freshness.status === "fresh" && Date.now() - _catalogLastCheck < 5 * 60 * 1000) return;
  _catalogLastCheck = Date.now();
  try {
    await refreshCatalog();
    render();
  } catch (error) {
    if (inspectCatalogFreshness(App.catalogSyncAt).status !== "fresh") {
      invalidateStaleCatalog(error);
    }
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") revalidateCatalog();
});
window.addEventListener("focus", () => revalidateCatalog());

function catalogLoadMessage(error) {
  if (error?.code === "CATALOG_ROLLBACK") {
    return "Сервер вернул ревизию каталога ниже ранее подтверждённой на этом устройстве. Каталог не загружен. Проверьте опубликованную версию или повторите попытку позже.";
  }
  if (error?.code === "CATALOG_NOT_FRESH") {
    const at = error.freshness?.sourceUpdatedAt;
    const when = at ? fmtDate(at) : "не указана";
    return `Каталог временно скрыт: актуальность данных не подтверждена. Последняя синхронизация — ${when}. Повторите загрузку после обновления данных.`;
  }
  return "Не удалось получить актуальный каталог. Проверьте подключение и повторите попытку.";
}
boot();
