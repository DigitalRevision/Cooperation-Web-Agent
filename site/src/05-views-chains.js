/* ===== Производственные цепочки и замена поставщика ===== */

/* ---------- Пример цепочки и типы связей ---------- */
function exampleChain() {
  const n = (step, pid, extra = {}) => ({ id: uidGen(), step, company_id: App.P[pid].company_id, product_id: pid, status: "SELECTED", history: [], ...extra });
  const nodes = [
    n("Металлопрокат", "ko-round"),
    n("Механическая обработка", "kzbi-machining"),
    n("Термическая обработка", "kzbi-heat"),
    n("Подшипники", "epkv-bearings"),
    n("Насос (сборка изделия)", "vnm-pumps"),
    n("Подъёмное оборудование для монтажа", "ukz-hoists"),
  ];
  const edges = nodes.slice(1).map((to, i) => ({ from: nodes[i].id, to: to.id, type: relType(nodes[i], to), qty: "", unit: "", price: "", min_batch: "", lead_prod: "", lead_deliv: "" }));
  return { id: "chain-" + uidGen(), title: "Насосный агрегат — пример из потенциальных связей", buyer_city: App.profile.city, nodes, edges, created_at: nowIso() };
}
function relType(a, b) {
  const r = App.data.relations.find((x) => x.from === a.company_id && x.to === b.company_id);
  return r ? r.type : "INFERRED_RELATION";
}
function edgeFor(ch, fromId, toId) { return ch.edges.find((e) => e.from === fromId && e.to === toId); }

/* ---------- Список цепочек ---------- */
ROUTES.chains = () => {
  return `<div class="wrap page">${crumbs(["#chains", "Производственные цепочки"])}
  <div class="sec-h"><h1 class="h1">Производственные цепочки</h1><div class="row"><button class="btn" data-act="chain-example">Создать из примера</button><button class="btn pri" data-act="chain-new">Новая цепочка</button></div></div>
  <p class="muted" style="max-width:760px">Постройте цепочку от поставщика металла до готового изделия. Каждый этап — отдельное предприятие. Если поставщик отказался, замените его на узле — цепочка сохранится.</p>
  <div class="legend" style="margin:12px 0 24px"><span><i></i>CONFIRMED — подтверждена сторонами</span><span><i class="p"></i>POTENTIAL — возможна по данным источников</span><span><i class="n"></i>INFERRED — вывод системы</span></div>
  ${App.chains.length ? App.chains.map((ch) => `<article class="card" style="margin-bottom:12px"><div class="card-head"><div><h3 class="h3"><a href="#ch.${esc(ch.id)}">${esc(ch.title)}</a></h3><div class="muted">${ch.nodes.length} ${plural(ch.nodes.length, "этап", "этапа", "этапов")} · изменена ${fmtDate(ch.updated_at)}</div></div><a class="btn sm" href="#ch.${esc(ch.id)}">Открыть</a></div>
    <div class="muted" style="margin-top:8px">${ch.nodes.map((nd) => esc(nd.step) + ": " + esc(nd.company_id ? App.C[nd.company_id]?.short : "не выбран")).join(" → ")}</div></article>`).join("")
    : `<div class="note">Цепочек пока нет. Начните с примера — он собран из реальных предприятий базы, связи помечены как выводы системы.</div>`}
  </div>`;
};

/* ---------- Страница цепочки: узлы, связи, действия ---------- */
ROUTES.ch = (id) => {
  const ch = App.chains.find((c) => c.id === id);
  if (!ch) return `<div class="wrap page">${crumbs(["#chains", "Производственные цепочки"], ["", "Цепочка"])}<div class="note">Цепочка не найдена или ещё загружается.</div></div>`;
  const parts = [];
  ch.nodes.forEach((nd, i) => {
    if (i > 0) { const e = edgeFor(ch, ch.nodes[i - 1].id, nd.id) || { type: "INFERRED_RELATION" }; parts.push(`<button class="edge ${e.type}" data-act="edge-edit" data-chain="${esc(ch.id)}" data-from="${esc(ch.nodes[i - 1].id)}" data-to="${esc(nd.id)}" aria-label="Параметры связи" style="background:none;border:0;cursor:pointer"><span>${e.type.split("_")[0]}</span></button>`); }
    const c = nd.company_id ? App.C[nd.company_id] : null, p = nd.product_id ? App.P[nd.product_id] : null;
    parts.push(`<div class="node ${nd.status === "DECLINED" ? "declined" : ""} ${UI.selNode === nd.id ? "sel" : ""}">
      <div class="step">Этап ${i + 1} · ${esc(nd.step)}</div>
      ${c ? `<div class="org"><a href="#c.${esc(c.id)}">${esc(c.short)}</a></div><div>${p ? `<a href="#p.${esc(p.id)}">${esc(p.name)}</a>` : "Позиция не выбрана"}</div><div class="muted">${esc(c.city)} · ${okvedTag(c.okved_main)}</div><div>${statusBadge(c.verification_status)}</div>`
        : `<div class="org" style="color:var(--ink-muted)">Поставщик не выбран</div>`}
      ${nd.status === "DECLINED" ? `<div class="v no">Поставщик отказался</div>` : ""}
      ${nd.history?.length ? `<div class="muted">Замен: ${nd.history.length}</div>` : ""}
      <div class="acts">
        <button class="btn sm ${nd.status === "DECLINED" || !c ? "pri" : ""}" data-act="replace" data-chain="${esc(ch.id)}" data-node="${esc(nd.id)}">${c ? "Заменить поставщика" : "Найти поставщика"}</button>
        ${c && nd.status !== "DECLINED" ? `<button class="btn sm txt" data-act="declined" data-chain="${esc(ch.id)}" data-node="${esc(nd.id)}">Отказался</button>` : ""}
        <button class="btn sm txt" data-act="node-edit" data-chain="${esc(ch.id)}" data-node="${esc(nd.id)}">Этап</button>
        <button class="btn sm txt" data-act="node-del" data-chain="${esc(ch.id)}" data-node="${esc(nd.id)}" aria-label="Удалить этап">Удалить</button>
      </div></div>`);
  });
  return `<div class="wrap page">${crumbs(["#chains", "Производственные цепочки"], ["", ch.title])}
  <div class="sec-h"><div><h1 class="h1">${esc(ch.title)}</h1><div class="muted">Город покупателя: ${esc(ch.buyer_city || App.profile.city)} · изменена ${fmtDate(ch.updated_at)}</div></div>
    <div class="row"><button class="btn" data-act="node-add" data-chain="${esc(ch.id)}">Добавить этап</button><button class="btn" data-act="chain-rename" data-chain="${esc(ch.id)}">Переименовать</button><button class="btn danger" data-act="chain-del" data-chain="${esc(ch.id)}">Удалить</button></div></div>
  <div class="chain" role="list">${parts.join("") || '<div class="note">В цепочке нет этапов.</div>'}</div>
  <div class="legend"><span><i></i>CONFIRMED — подтверждена сторонами</span><span><i class="p"></i>POTENTIAL — возможна по данным</span><span><i class="n"></i>INFERRED — вывод системы</span><span>Нажмите на стрелку, чтобы указать объём, цену, сроки связи.</span></div>
  <section class="sec"><h2 class="h2" style="margin-bottom:12px">Связи цепочки</h2>
    <div class="tbl-wrap"><table class="tbl"><thead><tr><th>От</th><th>К</th><th>Тип</th><th>Продукт</th><th>ОКПД2</th><th>ОКВЭД поставщика</th><th>Объём</th><th>Цена</th><th>Мин. партия</th><th>Срок произв.</th><th>Срок поставки</th><th>Регион</th><th>Расстояние</th><th>Источник</th></tr></thead><tbody>
    ${ch.nodes.slice(1).map((nd, i) => { const a = ch.nodes[i], e = edgeFor(ch, a.id, nd.id) || {}; const ca = App.C[a.company_id], pa = App.P[a.product_id], cb = App.C[nd.company_id];
      const d = ca && cb ? distanceKm(ca.city, cb.city) : null;
      return `<tr><td>${ca ? esc(ca.short) : unk("na")}</td><td>${cb ? esc(cb.short) : unk("na")}</td><td>${relBadge(e.type || "INFERRED_RELATION")}</td><td>${pa ? esc(pa.name) : unk("na")}</td><td>${pa ? okpdTag(pa.okpd2) : unk("na")}</td><td>${ca ? okvedTag(ca.okved_main) : unk("na")}</td>
      <td>${e.qty ? esc(e.qty + " " + (e.unit || "")) : unk("na")}</td><td>${e.price ? priceHtml({ value: e.price, unit: e.unit }) : unk("price")}</td><td>${e.min_batch ? esc(e.min_batch) : unk("na")}</td><td>${e.lead_prod ? esc(e.lead_prod) : unk("na")}</td><td>${e.lead_deliv ? esc(e.lead_deliv) : unk("na")}</td>
      <td>${ca ? esc(ca.city) : ""}</td><td class="num">${d != null ? d + " км" : unk("na")}</td><td>${pa ? srcBtn(pa.source_id) : ""}</td></tr>`; }).join("") || '<tr><td colspan="14" class="muted">Добавьте минимум два этапа.</td></tr>'}
    </tbody></table></div>
    <p class="muted">Значения объёма, цены и сроков вносит пользователь по итогам переговоров — они помечаются как указанные пользователем. Склад: данные о складских остатках поставщиков не опубликованы.</p>
  </section>
  ${ch.nodes.some((n) => n.history?.length) ? `<section class="sec"><h2 class="h2" style="margin-bottom:12px">История замен</h2><ul class="list">${ch.nodes.flatMap((n) => (n.history || []).map((h) => `<li><span>${esc(n.step)}: ${esc(App.C[h.company_id]?.short || "—")} → ${esc(App.C[h.to]?.short || "—")}${h.reason ? " · " + esc(h.reason) : ""}</span><span class="muted">${fmtDate(h.at)}</span></li>`)).join("")}</ul></section>` : ""}
  </div>`;
};

// Поисковый запрос для этапа цепочки
function nodeQuery(ch, nd) {
  const p = nd.product_id ? App.P[nd.product_id] : null;
  const base = [nd.req_text || "", p ? p.name : "", nd.step].join(" ");
  const q = parseQuery(base);
  if (p?.okpd2) q.okpd2 = p.okpd2.code;
  if (p && !q.products.length && !q.technologies.length) {
    const words = p.name.toLowerCase().split(/[^а-яё]+/).filter((w) => w.length >= 5).slice(0, 2).map((w) => w.slice(0, 6));
    q.products = [{ label: p.name, stems: words }];
  }
  if (p?.kind === "service") { q.okved = null; }
  // регион текущего поставщика: альтернатива из того же региона получает совпадение по географии
  const cur = nd.company_id ? App.C[nd.company_id] : null;
  if (cur) { q.region = cur.region; q.regionName = regionName(cur.region); }
  q.missing = [];
  return q;
}

/* ---------- Замена поставщика в узле ---------- */
function openReplace(chainId, nodeId) {
  const ch = App.chains.find((c) => c.id === chainId), nd = ch?.nodes.find((n) => n.id === nodeId); if (!nd) return;
  UI.selNode = nodeId;
  const q = nodeQuery(ch, nd);
  const cur = nd.company_id ? matchCompany(q, App.C[nd.company_id], { city: ch.buyer_city || App.profile.city }) : null;
  const alts = searchCompanies(q, { includeUnverified: UI.replUnv, city: ch.buyer_city || App.profile.city, exclude: nd.company_id ? [nd.company_id] : [] });
  const crits = [...new Set([...(cur ? cur.crit : []), ...alts.flatMap((m) => m.crit)].map((x) => x.n))];
  const cell = (m, n) => { const x = m.crit.find((y) => y.n === n); return x ? `<span class="v ${x.r}" title="${esc(x.why.replace(/<[^>]+>/g, ""))}">${V_TXT[x.r]}</span>` : '<span class="v skip">—</span>'; };
  const row = (m, isCur) => `<tr><td><b><a href="#c.${esc(m.c.id)}" data-close>${esc(m.c.short)}</a></b>${isCur ? '<br><span class="muted">текущий</span>' : ""}<br>${statusBadge(m.c.verification_status)}<div class="muted">${m.prods.slice(0, 2).map((p) => esc(p.name)).join("; ")}</div></td>
    ${crits.map((n) => `<td>${cell(m, n)}</td>`).join("")}<td class="num">${m.dist != null ? (m.dist === 0 ? "тот же город" : m.dist + " км") : unk("na")}</td><td>${unk("price")}</td><td>${unk("na")}</td><td><span class="score">${m.yes} из ${m.applicable}</span></td>
    <td>${isCur ? "" : `<button class="btn sm pri" data-act="pick" data-chain="${esc(chainId)}" data-node="${esc(nodeId)}" data-company="${esc(m.c.id)}" data-product="${m.prods[0]?.id || ""}">Выбрать</button>`}</td></tr>`;
  openPanel(`<div class="panel-h"><div><div class="label">Замена поставщика · этап «${esc(nd.step)}»</div><h2 class="h2">Альтернативы из проверенной базы</h2></div><button class="x" data-close aria-label="Закрыть">×</button></div>
    ${queryChips(q)}
    <div class="row" style="margin:12px 0"><label class="chk"><input type="checkbox" id="repl-unv" ${UI.replUnv ? "checked" : ""}> Показывать неподтверждённые данные</label></div>
    <p class="muted">Порядок — по числу подтверждённых совпадений. Система не выбирает поставщика за вас. Цены, мин. партия, наличие, сроки не опубликованы предприятиями.</p>
    <div class="tbl-wrap"><table class="tbl sticky"><thead><tr><th>Предприятие</th>${crits.map((n) => `<th>${esc(n)}</th>`).join("")}<th>Расстояние</th><th>Цена</th><th>Мин. партия</th><th>Подтверждено</th><th></th></tr></thead>
    <tbody>${cur ? row(cur, true) : ""}${alts.map((m) => row(m, false)).join("")}</tbody></table></div>
    ${alts.length ? "" : `<div class="note" style="margin-top:12px">Альтернатив в базе не найдено. Расширьте поиск: <button class="btn sm" data-act="repl-request" data-chain="${esc(chainId)}" data-node="${esc(nodeId)}">Создать заявку на этап</button> — её увидят новые предприятия.</div>`}
    <p class="muted" style="margin-top:12px">Нажмите «Выбрать», чтобы поставить предприятие в узел. Остальные этапы и связи цепочки сохранятся, предыдущий поставщик попадёт в историю замен.</p>`);
  const cb = $("#repl-unv"); cb && cb.addEventListener("change", () => { UI.replUnv = cb.checked; openReplace(chainId, nodeId); });
}
async function pickSupplier(chainId, nodeId, companyId, productId) {
  const ch = JSON.parse(JSON.stringify(App.chains.find((c) => c.id === chainId)));
  const nd = ch.nodes.find((n) => n.id === nodeId);
  nd.history = nd.history || [];
  nd.history.push({ company_id: nd.company_id, to: companyId, at: nowIso(), reason: nd.status === "DECLINED" ? "поставщик отказался" : "замена пользователем" });
  nd.company_id = companyId; nd.product_id = productId || null; nd.status = "SELECTED";
  const i = ch.nodes.indexOf(nd);
  for (const e of ch.edges) { if (e.to === nd.id && i > 0) e.type = relType(ch.nodes[i - 1], nd); if (e.from === nd.id && ch.nodes[i + 1]) e.type = relType(nd, ch.nodes[i + 1]); }
  closePanel(); await Store.saveChain(ch); toast("Поставщик заменён. Остальные этапы сохранены.");
}

/* ---------- Панели: добавить в цепочку, редактировать узел и связь ---------- */
function addToChainPanel(companyId, productId) {
  const c = App.C[companyId] || App.C[App.P[productId]?.company_id];
  openPanel(`<div class="panel-h"><div><div class="label">Добавить в производственную цепочку</div><h2 class="h2">${esc(productId ? App.P[productId].name : c.name)}</h2></div><button class="x" data-close aria-label="Закрыть">×</button></div>
  <form id="to-chain-form" class="form" data-company="${esc(c.id)}" data-product="${productId || ""}">
    <div class="field full"><label for="tc-chain">Цепочка</label><select class="sel" id="tc-chain" name="chain"><option value="__new">Новая цепочка</option>${App.chains.map((ch) => `<option value="${esc(ch.id)}">${esc(ch.title)}</option>`).join("")}</select></div>
    <div class="field full"><label for="tc-step">Название этапа</label><input class="inp" id="tc-step" name="step" required value="${esc(productId ? App.P[productId].category : c.subindustry)}"></div>
    ${productId ? "" : `<div class="field full"><label for="tc-prod">Позиция</label><select class="sel" id="tc-prod" name="product">${c.products.map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join("")}</select></div>`}
    <div class="full row"><button class="btn pri" type="submit">Добавить этап</button></div></form>`, "narrow");
}
function nodeEditPanel(chainId, nodeId) {
  const ch = App.chains.find((c) => c.id === chainId); const nd = nodeId ? ch.nodes.find((n) => n.id === nodeId) : null;
  openPanel(`<div class="panel-h"><div><div class="label">${nd ? "Этап цепочки" : "Новый этап"}</div><h2 class="h2">${nd ? esc(nd.step) : "Добавить этап"}</h2></div><button class="x" data-close aria-label="Закрыть">×</button></div>
  <form id="node-form" class="form" data-chain="${esc(chainId)}" data-node="${nodeId || ""}">
    <div class="field full"><label for="nf-step">Название этапа *</label><input class="inp" id="nf-step" name="step" required value="${esc(nd?.step || "")}" placeholder="например: Термическая обработка"></div>
    <div class="field full"><label for="nf-req">Требование к поставщику</label><input class="inp" id="nf-req" name="req_text" value="${esc(nd?.req_text || "")}" placeholder="например: термообработка деталей до 6 м"></div>
    <div class="full row"><button class="btn pri" type="submit">Сохранить</button></div></form>`, "narrow");
}
function edgeEditPanel(chainId, from, to) {
  const ch = App.chains.find((c) => c.id === chainId); let e = edgeFor(ch, from, to) || {};
  openPanel(`<div class="panel-h"><div><div class="label">Связь цепочки</div><h2 class="h2">${esc(App.C[ch.nodes.find((n) => n.id === from)?.company_id]?.short || "—")} → ${esc(App.C[ch.nodes.find((n) => n.id === to)?.company_id]?.short || "—")}</h2></div><button class="x" data-close aria-label="Закрыть">×</button></div>
  <form id="edge-form" class="form" data-chain="${esc(chainId)}" data-from="${from}" data-to="${to}">
    <div class="field full"><label for="ef-type">Тип связи</label><select class="sel" id="ef-type" name="type">${["INFERRED_RELATION", "POTENTIAL_RELATION", "CONFIRMED_RELATION"].map((t) => `<option value="${t}" ${e.type === t ? "selected" : ""}>${REL_TXT[t]}</option>`).join("")}</select>
      <span class="muted">CONFIRMED ставьте только при наличии договора или письменного подтверждения обеих сторон.</span></div>
    <div class="field"><label for="ef-qty">Объём</label><input class="inp" id="ef-qty" name="qty" value="${esc(e.qty || "")}"></div>
    <div class="field"><label for="ef-unit">Единица</label><input class="inp" id="ef-unit" name="unit" value="${esc(e.unit || "")}" placeholder="т/мес"></div>
    <div class="field"><label for="ef-price">Цена, ₽</label><input class="inp" id="ef-price" name="price" value="${esc(e.price || "")}" inputmode="decimal"></div>
    <div class="field"><label for="ef-min">Мин. партия</label><input class="inp" id="ef-min" name="min_batch" value="${esc(e.min_batch || "")}"></div>
    <div class="field"><label for="ef-lp">Срок производства</label><input class="inp" id="ef-lp" name="lead_prod" value="${esc(e.lead_prod || "")}"></div>
    <div class="field"><label for="ef-ld">Срок поставки</label><input class="inp" id="ef-ld" name="lead_deliv" value="${esc(e.lead_deliv || "")}"></div>
    <div class="full row"><button class="btn pri" type="submit">Сохранить связь</button></div></form>`, "narrow");
}
