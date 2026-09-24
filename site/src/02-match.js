/* ===== AI Parser → Structured Query → сопоставление по проверенной базе ===== */

/* Словарь предметной области: ключевые основы → продукт, класс ОКПД2, ОКВЭД. Это правила разбора, а не данные о предприятиях. */
const LEX = [
  { re: /насос/, label: "насос", stems: ["насос"], okpd2: "28.13", okved: "28.13" },
  { re: /компрессор/, label: "компрессор", stems: ["компрессор"], okpd2: "28.13", okved: "28.13" },
  { re: /арматур/, label: "трубопроводная арматура", stems: ["арматур"], okpd2: "28.14" },
  { re: /кран|козлов|мостов/, label: "кран", stems: ["кран"], okpd2: "28.22", okved: "28.22.42" },
  { re: /(?<![а-я])тал[иья]|тельфер/, label: "таль", stems: ["тал", "тельфер"], okpd2: "28.22" },
  { re: /грейфер/, label: "грейферная тележка", stems: ["грейфер"], okpd2: "28.22" },
  { re: /подшипник/, label: "подшипник", stems: ["подшипник"], okpd2: "28.15", okved: "28.15.1" },
  { re: /резонатор|кварц/, label: "кварцевый резонатор", stems: ["резонатор", "кварц"], okpd2: "26.11", okved: "26.11.2" },
  { re: /генератор/, label: "генератор", stems: ["генератор"], okpd2: "26.11" },
  { re: /труб(?!опровод|н)/, label: "труба", stems: ["труб"], okpd2: "24.20" },
  { re: /трубн\w* заготов|заготовк|блюм/, label: "заготовка", stems: ["заготовк", "блюм"], okpd2: "24.10", okved: "24.10.6" },
  { re: /прокат|лист/, label: "прокат", stems: ["прокат"], okpd2: "24.10", okved: "24.10.6" },
  { re: /штанг|коронк|перфоратор|буров/, label: "буровой инструмент", stems: ["штанг", "коронк", "буров"], okpd2: "28.92", okved: "28.92" },
  { re: /оправк|прошивн|раскатн/, label: "оправки для трубных станов", stems: ["оправк"], okpd2: "28.91" },
  { re: /абразив|шлиф/, label: "абразивный инструмент", stems: ["абразив", "шлиф"], okpd2: "23.91" },
  { re: /карбид/, label: "карбид кремния", stems: ["карбид"], okpd2: "20.13", okved: "20.13" },
  { re: /огнеупор/, label: "огнеупоры", stems: ["огнеупор"], okpd2: "23.20" },
  { re: /резервуар|ёмкост|емкост/, label: "резервуар", stems: ["резервуар"], okpd2: "25.29" },
  { re: /металлоконструкц|дымов/, label: "металлоконструкции", stems: ["металлоконструкц", "дымов"], okpd2: "25.11", okved: "25.11" },
  { re: /котл|котель/, label: "котельное оборудование", stems: ["котель"] },
  { re: /сосуд/, label: "сосуд под давлением", stems: ["сосуд"] },
  { re: /судов|двер|люк/, label: "судовые закрытия", stems: ["судов", "двер", "люк"] },
  { re: /катализатор/, label: "катализатор", stems: ["катализатор"], okpd2: "20.59" },
  { re: /запчаст|запасн/, label: "запчасти", stems: ["запчаст"] },
];
const TECH_LEX = [
  { re: /термообработ|термическ|закалк|отпуск/, label: "термическая обработка", stems: ["термическ", "термообработ"], okpd2: "25.61" },
  { re: /мехобработ|механообработ|механическ\w* обработ|токарн|фрезер/, label: "механическая обработка", stems: ["механическ", "фрезер", "токарн"], okpd2: "25.62" },
  { re: /штамповк|ковк|гкм/, label: "штамповка", stems: ["штамповк"], okpd2: "25.50" },
  { re: /сварк|сварн/, label: "сварка", stems: ["сварк", "сварн"] },
  { re: /резк|раскрой/, label: "резка", stems: ["резк", "раскрой"], okpd2: "25.62" },
  { re: /неразрушающ|дефектоскоп|испытан/, label: "неразрушающий контроль", stems: ["неразрушающ", "испытан"] },
  { re: /вальцовк|вальц/, label: "вальцовка", stems: ["вальц"] },
  { re: /прокатн\w* производ/, label: "прокатное производство", stems: ["прокатн"] },
];
const MAT_LEX = [
  { re: /нержаве/, label: "нержавеющая сталь", stems: ["нержаве"] },
  { re: /стал[ьи]|стальн/, label: "сталь", stems: ["стал"] },
  { re: /чугун/, label: "чугун", stems: ["чугун"] },
  { re: /алюмини/, label: "алюминий", stems: ["алюмини"] },
  { re: /медь|медн/, label: "медь", stems: ["мед"] },
];
const INDUSTRY_LEX = [
  { re: /нефтегаз|нефт|газов/, label: "нефтегазовое оборудование", stems: ["нефтегаз", "газопровод", "нефт"] },
  { re: /атомн/, label: "атомная промышленность", stems: ["атомн"] },
  { re: /горн|шахт|рудн/, label: "горнодобывающая промышленность", stems: ["горн", "добыч"] },
  { re: /металлург|доменн/, label: "металлургия", stems: ["металлург", "доменн", "стан"] },
  { re: /судостро|судов/, label: "судостроение", stems: ["судов"] },
  { re: /электрон|радио/, label: "радиоэлектроника", stems: ["электрон", "пьезо"] },
];
const UNIT_MAP = [
  [/^(т|тн|тонн\w*)$/, "т"], [/^(кг|килограмм\w*)$/, "кг"], [/^(шт|штук\w*|ед|единиц\w*)$/, "шт"],
  [/^(м2|м²|кв\.?м)$/, "м²"], [/^(м3|м³|куб\.?м)$/, "м³"], [/^(м|метр\w*)$/, "м"], [/^(л|литр\w*)$/, "л"],
  [/^(компл\w*|комплект\w*)$/, "комплект"], [/^(парти\w*)$/, "партия"],
];
const REGION_LEX = [
  { re: /волгоград|волжск|камышин|урюпинск|михайловк|фролов/, region: "34" },
  { re: /орлов|ливн/, region: "57" },
  { re: /ростов/, region: null, name: "Ростовская область" }, { re: /астрахан/, region: null, name: "Астраханская область" },
  { re: /саратов/, region: null, name: "Саратовская область" }, { re: /воронеж/, region: null, name: "Воронежская область" },
  { re: /самар/, region: null, name: "Самарская область" }, { re: /москв/, region: null, name: "Москва / Московская область" },
  { re: /петербург|ленинград/, region: null, name: "Санкт-Петербург / Ленинградская область" },
];

function parseQuery(text) {
  const t = " " + String(text || "").toLowerCase().replace(/ё/g, "е") + " ";
  const q = { raw: text, products: [], technologies: [], material: null, grades: [], industry: null, okpd2: null, okved: null, volume: null, unit: null, period: null, region: null, regionName: null, city: null, missing: [], engine: "rules" };
  for (const l of LEX) if (l.re.test(t)) q.products.push(l);
  for (const l of TECH_LEX) if (l.re.test(t)) q.technologies.push(l);
  for (const l of MAT_LEX) if (l.re.test(t)) { q.material = l; break; }
  for (const l of INDUSTRY_LEX) if (l.re.test(t)) { q.industry = l; break; }
  const grades = (text || "").match(/\b\d{1,2}[ХГНМТЮСФКВРА]{1,}[0-9ХГНМТЮСФКВРА]*\b/g); if (grades) q.grades = grades;
  const vm = t.match(/(\d[\d\s]*[.,]?\d*)\s*(тонн\w*|тн|т|кг|килограмм\w*|шт|штук\w*|единиц\w*|м2|м²|м3|м³|метр\w*|м|литр\w*|л|комплект\w*|компл|парти\w*)(?=[\s.,;/]|$)/);
  if (vm) {
    q.volume = Number(vm[1].replace(/\s/g, "").replace(",", "."));
    const u = vm[2]; for (const [re, n] of UNIT_MAP) if (re.test(u)) { q.unit = n; break; }
  }
  if (/в месяц|\/мес|ежемесячн/.test(t)) q.period = "мес"; else if (/в год|\/год|ежегодн/.test(t)) q.period = "год";
  for (const r of REGION_LEX) if (r.re.test(t)) { q.region = r.region; q.regionName = r.region ? regionName(r.region) : r.name; break; }
  for (const c of Object.keys(App.data.cities)) if (t.includes(c.toLowerCase().slice(0, 6))) { q.city = c; break; }
  const p0 = q.products[0] || q.technologies[0];
  q.okpd2 = p0?.okpd2 || null; q.okved = q.products.find((p) => p.okved)?.okved || null;
  if (!q.products.length && !q.technologies.length && !q.industry) q.missing.push({ k: "product", t: "вид продукции или услуги не распознан — уточните, что требуется" });
  if (q.material && !q.okpd2) q.missing.push({ k: "okpd2", t: "ОКПД2 не определён — уточните вид изделия (лист, круг, заготовка, труба)" });
  if (q.volume == null) q.missing.push({ k: "volume", t: "объём не указан" });
  if (!q.region && !q.regionName) q.missing.push({ k: "region", t: "регион не указан — поиск по всей базе" });
  return q;
}

/* AI-разбор через Claude (если зритель разрешил): только структура запроса, без фактов о предприятиях */
async function parseWithClaude(text) {
  if (!App.sample) return null;
  const prompt = `Ты — разборщик промышленных запросов. Преобразуй запрос в JSON. НЕ называй предприятий, цен, объёмов производства или любых фактов — только структура запроса пользователя.
Схема: {"product_keywords":[строки в именительном падеже],"technology_keywords":[],"material":строка|null,"steel_grades":[],"industry":строка|null,"volume":число|null,"unit":"т"|"кг"|"шт"|"м"|"м²"|"м³"|"л"|"комплект"|"партия"|null,"period":"мес"|"год"|null,"region":строка|null,"okpd2_class_candidates":["XX.XX"],"okved_candidates":["XX.XX"]}
Если поле не следует из текста — null или пустой массив. Запрос: """${String(text).slice(0, 500)}"""`;
  const r = await App.sample.json(prompt, { modelTier: "quick" });
  const q = parseQuery([text, ...(r.product_keywords || []), ...(r.technology_keywords || []), r.material || "", r.industry || "", r.region || ""].join(" "));
  q.raw = text; q.engine = "claude";
  if (r.volume != null && q.volume == null) q.volume = r.volume;
  if (r.unit && !q.unit) q.unit = r.unit;
  if (r.period && !q.period) q.period = r.period;
  q.aiCandidates = { okpd2: r.okpd2_class_candidates || [], okved: r.okved_candidates || [] };
  if (!q.okpd2 && q.aiCandidates.okpd2[0] && App.data.okpd2[q.aiCandidates.okpd2[0]]) q.okpd2 = q.aiCandidates.okpd2[0];
  q.missing = q.missing.filter((m) => !(m.k === "volume" && q.volume != null));
  return q;
}

const hasStem = (s, stems) => { const x = String(s || "").toLowerCase().replace(/ё/g, "е"); return stems.some((st) => new RegExp("(?<![а-яa-z])" + st.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).test(x)); };

/* Сопоставление одного предприятия с запросом. Возвращает критерии с результатом и основанием. */
function matchCompany(q, c, opts = {}) {
  const crit = [];
  const prods = c.products.filter((p) => srcActive(p.source_id));
  const stems = q.products.flatMap((p) => p.stems);
  const tstems = q.technologies.flatMap((p) => p.stems);
  // PRODUCT_MATCH
  let prodHits = [];
  if (stems.length) {
    prodHits = prods.filter((p) => hasStem(p.name + " " + p.category + " " + (p.description || ""), stems));
    crit.push({ k: "PRODUCT_MATCH", n: "Продукция", r: prodHits.length ? "yes" : "no",
      why: prodHits.length ? prodHits.slice(0, 3).map((p) => esc(p.name)).join("; ") : "Нет совпадений в подтверждённой продукции", src: prodHits[0]?.source_id, prods: prodHits });
  } else if (q.industry) {
    prodHits = prods.filter((p) => hasStem(p.name + " " + (p.description || "") + " " + c.subindustry, q.industry.stems));
    const indHit = hasStem(c.subindustry + " " + c.industry, q.industry.stems);
    crit.push({ k: "PRODUCT_MATCH", n: "Отрасль / продукция", r: prodHits.length || indHit ? "compat" : "no",
      why: prodHits.length ? prodHits.slice(0, 3).map((p) => esc(p.name)).join("; ") : indHit ? "Отрасль: " + esc(c.subindustry) : "Не относится к отрасли запроса", src: prodHits[0]?.source_id, prods: prodHits });
  }
  // OKPD2_MATCH
  if (q.okpd2) {
    const hits = prods.filter((p) => p.okpd2 && (p.okpd2.code.startsWith(q.okpd2) || q.okpd2.startsWith(p.okpd2.code)));
    const srcHit = hits.find((p) => p.okpd2.status !== "INFERRED");
    crit.push({ k: "OKPD2_MATCH", n: "ОКПД2 " + q.okpd2, r: srcHit ? "yes" : hits.length ? "part" : "none",
      why: srcHit ? "Код указан в источнике" : hits.length ? "Совпадает по коду, присвоенному по классификатору — требует подтверждения" : "У продукции нет подходящего кода ОКПД2 в базе" });
    if (!prodHits.length && hits.length) prodHits = hits;
  }
  // OKVED
  if (q.okved) {
    if (!c.okved_main) crit.push({ k: "OKVED", n: "ОКВЭД " + q.okved, r: "none", why: "ОКВЭД предприятия не подтверждён" });
    else if (c.okved_main === q.okved || c.okved_main.startsWith(q.okved + ".")) crit.push({ k: "EXACT_OKVED_MATCH", n: "ОКВЭД " + q.okved, r: "yes", why: "Основной ОКВЭД " + c.okved_main + " (ЕГРЮЛ)", src: c.sources.find((s) => s.source_type === "EGRUL_AGGREGATOR")?.id });
    else if (c.okved_main.split(".")[0] === q.okved.split(".")[0]) crit.push({ k: "COMPATIBLE_OKVED", n: "ОКВЭД " + q.okved, r: "compat", why: "Основной ОКВЭД " + c.okved_main + " — тот же класс " + q.okved.split(".")[0], src: c.sources.find((s) => s.source_type === "EGRUL_AGGREGATOR")?.id });
    else crit.push({ k: "OKVED", n: "ОКВЭД " + q.okved, r: "no", why: "Основной ОКВЭД " + c.okved_main + " — другой вид деятельности" });
  }
  // MATERIAL_MATCH
  if (q.material || q.grades.length) {
    const mats = [...c.materials, ...prods.flatMap((p) => p.materials || [])];
    const want = q.grades.length ? q.grades.map((g) => g.toLowerCase()) : q.material.stems;
    const hit = mats.find((m) => hasStem(m.name, want));
    crit.push({ k: "MATERIAL_MATCH", n: "Материал: " + (q.grades.join(", ") || q.material.label), r: hit ? "yes" : mats.length ? "no" : "none",
      why: hit ? esc(hit.name) : mats.length ? "Другие материалы в источнике" : "Материалы в открытых источниках не указаны", src: hit?.source_id });
  }
  // TECHNOLOGY_MATCH
  if (tstems.length) {
    const hit = c.technologies.find((t) => hasStem(t.name, tstems)) || prods.find((p) => p.kind === "service" && hasStem(p.name, tstems));
    crit.push({ k: "TECHNOLOGY_MATCH", n: "Технология: " + q.technologies.map((t) => t.label).join(", "), r: hit ? "yes" : c.technologies.length ? "no" : "none",
      why: hit ? esc(hit.name) : c.technologies.length ? "Указаны другие технологии" : "Технологии в открытых источниках не указаны", src: hit?.source_id });
    if (hit && !prodHits.length) prodHits = prods.filter((p) => p.kind === "service" && hasStem(p.name, tstems));
  }
  // GEOGRAPHICAL_MATCH
  if (q.region) {
    crit.push({ k: "GEOGRAPHICAL_MATCH", n: "Регион", r: c.region === q.region ? "yes" : "no", why: esc(regionName(c.region) + ", " + c.city), src: c.sources[0]?.id });
  } else if (q.regionName) {
    crit.push({ k: "GEOGRAPHICAL_MATCH", n: "Регион", r: "no", why: esc(q.regionName + " ещё не подключена к базе. Предприятие: " + regionName(c.region)) });
  }
  // CAPACITY_MATCH / объём
  if (q.volume != null) {
    const cap = c.capacities.find((x) => !x.historical && x.unit && q.unit && x.unit.startsWith(q.unit));
    crit.push({ k: "CAPACITY_MATCH", n: `Объём ${q.volume} ${q.unit || ""}${q.period ? "/" + q.period : ""}`, r: cap ? "part" : "none",
      why: cap ? `Опубликовано: «${esc(cap.text)}». Достаточность для заявки подтверждает предприятие.` : "Производственная мощность и доступный объём не опубликованы", src: cap?.source_id });
  }
  const applicable = crit.length;
  const yes = crit.filter((x) => x.r === "yes").length;
  const substantive = crit.some((x) => (["PRODUCT_MATCH", "OKPD2_MATCH", "TECHNOLOGY_MATCH"].includes(x.k) && ["yes", "part", "compat"].includes(x.r)) || x.k === "EXACT_OKVED_MATCH");
  const dist = opts.city ? distanceKm(opts.city, c.city) : null;
  return { c, crit, yes, applicable, substantive, prods: prodHits, dist };
}

function searchCompanies(q, { includeUnverified = false, city = App.profile.city, exclude = [] } = {}) {
  return App.data.companies
    .filter((c) => !exclude.includes(c.id))
    .filter((c) => includeUnverified || c.verification_status === "VERIFIED" || c.verification_status === "PARTIALLY_VERIFIED")
    .map((c) => matchCompany(q, c, { city }))
    .filter((m) => m.substantive)
    .sort((a, b) => b.yes - a.yes || (a.dist ?? 1e9) - (b.dist ?? 1e9));
}

function verdictSummary(m) {
  const miss = m.crit.filter((x) => x.r === "none" || x.r === "part").length;
  if (m.crit.some((x) => x.r === "no")) return "Предприятие соответствует части критериев. Несовпадения отмечены ✕.";
  if (miss) return "Соответствует указанным критериям в пределах опубликованных данных; часть параметров требует подтверждения у поставщика.";
  return "Соответствует всем указанным критериям по данным источников. Условия поставки подтверждает предприятие.";
}
const V_TXT = { yes: "Совпадает", compat: "Совместимо", part: "Требует подтверждения", none: "Нет открытых данных", no: "Не совпадает", skip: "Не задано" };
function matchTable(m) {
  return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Критерий</th><th>Результат</th><th>Основание</th></tr></thead><tbody>
  ${m.crit.map((x) => `<tr><td>${esc(x.n)}<div class="muted" style="font-size:11px">${x.k}</div></td><td><span class="v ${x.r}">${V_TXT[x.r]}</span></td><td>${x.why} ${srcBtn(x.src)}</td></tr>`).join("")}
  </tbody></table></div>
  <div class="summary"><span class="score">${m.yes} из ${m.applicable}</span> критериев подтверждены источниками. ${verdictSummary(m)}</div>`;
}
function queryChips(q) {
  const chip = (k, v) => `<span class="chip"><b>${k}</b>${esc(v)}</span>`;
  const out = [];
  q.products.forEach((p) => out.push(chip("product", p.label)));
  q.technologies.forEach((p) => out.push(chip("technology", p.label)));
  if (q.industry) out.push(chip("industry", q.industry.label));
  if (q.material) out.push(chip("material", q.material.label));
  q.grades.forEach((g) => out.push(chip("grade", g)));
  if (q.volume != null) out.push(chip("volume", String(q.volume)));
  if (q.unit) out.push(chip("unit", q.unit + (q.period ? "/" + q.period : "")));
  if (q.regionName) out.push(chip("region", q.regionName));
  if (q.okpd2) out.push(chip("okpd2", q.okpd2 + " " + (App.data.okpd2[q.okpd2] || "")));
  if (q.okved) out.push(chip("okved", q.okved));
  q.missing.forEach((m) => out.push(`<span class="chip miss"><b>${m.k}</b>${esc(m.t)}</span>`));
  return `<div class="chips"><span class="label">${q.engine === "claude" ? "Распознано AI (Claude) из запроса:" : "Распознано из запроса:"}</span>${out.join("")}</div>`;
}
