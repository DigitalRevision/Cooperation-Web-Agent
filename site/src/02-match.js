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
  { re: /трубн[а-яё]* заготов|заготовк|блюм/, label: "заготовка", stems: ["заготовк", "блюм"], okpd2: "24.10", okved: "24.10.6" },
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
// Технологии и виды обработки
const TECH_LEX = [
  { re: /термообработ|термическ|закалк|отпуск/, label: "термическая обработка", stems: ["термическ", "термообработ"], okpd2: "25.61" },
  { re: /мехобработ|механообработ|механическ[а-яё]* обработ|токарн|фрезер/, label: "механическая обработка", stems: ["механическ", "фрезер", "токарн"], okpd2: "25.62" },
  { re: /штамповк|ковк|гкм/, label: "штамповка", stems: ["штамповк"], okpd2: "25.50" },
  { re: /сварк|сварн|свароч/, label: "сварка", stems: ["сварк", "сварн", "свароч"] },
  { re: /резк|раскрой/, label: "резка", stems: ["резк", "раскрой"], okpd2: "25.62" },
  { re: /неразрушающ|дефектоскоп|испытан/, label: "неразрушающий контроль", stems: ["неразрушающ", "испытан"] },
  { re: /вальцовк|вальц/, label: "вальцовка", stems: ["вальц"] },
  { re: /прокатн[а-яё]* производ/, label: "прокатное производство", stems: ["прокатн"] },
];
// Материалы и марки стали
const MAT_LEX = [
  { re: /нержаве/, label: "нержавеющая сталь", stems: ["нержаве"] },
  { re: /стал[ьи]|стальн/, label: "сталь", stems: ["стал"] },
  { re: /чугун/, label: "чугун", stems: ["чугун"] },
  { re: /алюмини/, label: "алюминий", stems: ["алюмини"] },
  { re: /медь|медн/, label: "медь", stems: ["мед"] },
];
// Отрасли
const INDUSTRY_LEX = [
  { re: /нефтегаз|нефт|газов/, label: "нефтегазовое оборудование", stems: ["нефтегаз", "газопровод", "нефт"] },
  { re: /атомн/, label: "атомная промышленность", stems: ["атомн"] },
  { re: /горн|шахт|рудн/, label: "горнодобывающая промышленность", stems: ["горн", "добыч"] },
  { re: /металлург|доменн/, label: "металлургия", stems: ["металлург", "доменн", "стан"] },
  { re: /судостро|судов/, label: "судостроение", stems: ["судов"] },
  { re: /электрон|радио/, label: "радиоэлектроника", stems: ["электрон", "пьезо"] },
];
// Единицы измерения объёма
const UNIT_MAP = [
  [/^(т|тн|тонн[а-яё]*)$/, "т"], [/^(кг|килограмм[а-яё]*)$/, "кг"], [/^(шт|штук[а-яё]*|ед|единиц[а-яё]*)$/, "шт"],
  [/^(м2|м²|кв\.?м)$/, "м²"], [/^(м3|м³|куб\.?м)$/, "м³"], [/^(м|метр[а-яё]*)$/, "м"], [/^(л|литр[а-яё]*)$/, "л"],
  [/^(компл[а-яё]*|комплект[а-яё]*)$/, "комплект"], [/^(парти[а-яё]*)$/, "партия"],
];
// Регионы: все субъекты РФ, коды как в sync/config.py, те же шаблоны и порядок, что в backend/app/matching.py.
// Берётся первый совпавший; шаблон ищется с начала слова
const REGION_LEX = [
  ["волгоград|волжск|камышин|урюпинск|михайловк|фролов", "34", "Волгоградская область"], ["орлов|ливн", "57", "Орловская область"],
  ["ростов", "61", "Ростовская область"], ["астрахан", "30", "Астраханская область"], ["саратов", "64", "Саратовская область"],
  ["воронеж", "36", "Воронежская область"], ["калмык|элист", "08", "Республика Калмыкия"],
  ["адыге|майкоп", "01", "Республика Адыгея"], ["башкир|башкорт", "02", "Республика Башкортостан"], ["бурят|улан-удэ", "03", "Республика Бурятия"],
  ["алтайск|барнаул", "22", "Алтайский край"], ["алта[йе]", "04", "Республика Алтай"], ["дагестан|махачкал", "05", "Республика Дагестан"],
  ["ингуш", "06", "Республика Ингушетия"], ["кабардин|нальчик", "07", "Кабардино-Балкарская Республика"],
  ["карачаев|черкесск", "09", "Карачаево-Черкесская Республика"], ["карели|петрозаводск", "10", "Республика Карелия"],
  ["коми(?![а-я])|сыктывкар", "11", "Республика Коми"], ["марий|йошкар", "12", "Республика Марий Эл"], ["мордов|саранск", "13", "Республика Мордовия"],
  ["якут", "14", "Республика Саха (Якутия)"], ["осети|владикавказ", "15", "Республика Северная Осетия — Алания"],
  ["татарст|казан", "16", "Республика Татарстан"], ["тыв[аеы]|кызыл", "17", "Республика Тыва"], ["удмурт|ижевск", "18", "Удмуртская Республика"],
  ["хакас|абакан", "19", "Республика Хакасия"], ["чечн|чеченск|грозн", "20", "Чеченская Республика"], ["чуваш|чебоксар", "21", "Чувашская Республика"],
  ["краснодар|кубан", "23", "Краснодарский край"], ["красноярск", "24", "Красноярский край"], ["приморск|владивосток", "25", "Приморский край"],
  ["ставропол", "26", "Ставропольский край"], ["хабаровск", "27", "Хабаровский край"], ["амурск|благовещенск", "28", "Амурская область"],
  ["архангельск", "29", "Архангельская область"], ["белгород", "31", "Белгородская область"], ["брянск", "32", "Брянская область"],
  ["владимир", "33", "Владимирская область"], ["вологод|череповец", "35", "Вологодская область"], ["иванов", "37", "Ивановская область"],
  ["иркутск", "38", "Иркутская область"], ["калининград", "39", "Калининградская область"], ["калуж|калуг", "40", "Калужская область"],
  ["камчат", "41", "Камчатский край"], ["кемеров|кузбасс|новокузнецк", "42", "Кемеровская область — Кузбасс"], ["киров", "43", "Кировская область"],
  ["костром", "44", "Костромская область"], ["курган", "45", "Курганская область"], ["курск", "46", "Курская область"],
  ["ленинград", "47", "Ленинградская область"], ["липецк", "48", "Липецкая область"], ["магадан", "49", "Магаданская область"],
  ["московск|подмосков", "50", "Московская область"], ["мурманск", "51", "Мурманская область"],
  ["нижегород|нижн[а-я]* новгород", "52", "Нижегородская область"], ["новгород", "53", "Новгородская область"],
  ["новосибирск", "54", "Новосибирская область"], ["омск", "55", "Омская область"], ["оренбург", "56", "Оренбургская область"],
  ["пенз", "58", "Пензенская область"], ["перм", "59", "Пермский край"], ["псков", "60", "Псковская область"], ["рязан", "62", "Рязанская область"],
  ["самар|тольятти", "63", "Самарская область"], ["сахалин", "65", "Сахалинская область"], ["свердловск|екатеринбург", "66", "Свердловская область"],
  ["смоленск", "67", "Смоленская область"], ["тамбов", "68", "Тамбовская область"], ["тверск|твер[ьи](?![а-я])", "69", "Тверская область"],
  ["томск", "70", "Томская область"], ["тул[аеьы]|тульск", "71", "Тульская область"], ["тюмен", "72", "Тюменская область"],
  ["ульянов", "73", "Ульяновская область"], ["челябинск", "74", "Челябинская область"], ["забайкал|чита", "75", "Забайкальский край"],
  ["ярослав", "76", "Ярославская область"], ["москв", "77", "Москва"], ["петербург|спб", "78", "Санкт-Петербург"],
  ["еврейск|биробиджан", "79", "Еврейская автономная область"], ["ямало|ямал", "89", "Ямало-Ненецкий автономный округ"],
  ["ненецк", "83", "Ненецкий автономный округ"], ["ханты|югр|сургут", "86", "Ханты-Мансийский автономный округ — Югра"],
  ["чукот", "87", "Чукотский автономный округ"], ["запорож", "90", "Запорожская область"], ["крым|симферопол", "91", "Республика Крым"],
  ["севастопол", "92", "Севастополь"], ["донецк|днр", "93", "Донецкая Народная Республика"], ["луганск|лнр", "94", "Луганская Народная Республика"],
  ["херсон", "95", "Херсонская область"],
].map(([re, region, name]) => ({ re: new RegExp(`(?<![а-яa-z])(?:${re})`), region, name }));

// Слова запроса, которых нет в словарях (реестр Минпромторга — тысячи наименований вне словаря), ищутся в названиях продукции.
// Не ищутся служебные слова заявки: «нужен», «поставка», «производство», единицы, регионы. Те же правила — backend/app/matching.py
const FREE_STOP = /^(нуж|требует|требуют|купит|закуп|заказ|поставк|поставщ|поставит|доставк|производств|производител|изготовлен|изготовит|изготавлива|предприят|завод|компани|организац|фирм|срочн|недорог|оптов|оборудован|продукц|издели|товар|услуг|област|район|республик|росси|ищем|найти|можно|очень|также|котор|как(ой|ая|ие|ое|ую|их)|любо|любы|други|друго|штук|тонн|килограмм|метр|литр|комплект|месяц|недел|ежемесяч|ежегод|объем|количеств|размер|срок|качеств|интерес|предлож|подскаж|через|около|более|менее|всего|этого|этой|этих|сейчас|сегодня|желательно|примерно|чтобы|хотим|хочу|прошу|просим|гост|промышлен|работ)|^(цена|цены|цену|цене|опт|оптом|партия|партии|партию|край|крае|город|города|есть|плюс|года|лет|либо|если|тоже|надо|свой|свое|свои|наша|наши|ваша|ваши)$/;
// Основа слова без окончания: «кабель» → «кабел», «симметричный» → «симметричн», «шина» → «шин»
const freeStem = (w) => (w.length >= 7 ? w.slice(0, -2) : w.length >= 5 || /[аяоеуюыи]$/.test(w) ? w.slice(0, -1) : w);
// Сколько основ из n должно встретиться в названии позиции: два слова — оба, дальше — не меньше 60 %
const freeRequired = (n) => (n <= 2 ? n : Math.ceil(n * 3 / 5));
function freeWords(t) {
  const known = [...LEX, ...TECH_LEX, ...MAT_LEX, ...INDUSTRY_LEX, ...REGION_LEX].map((l) => l.re);
  const cities = Object.keys(App.data?.cities || {}).map((c) => c.toLowerCase().replace(/ё/g, "е").slice(0, 5));
  const words = [...new Set(t.match(/[а-яa-z][а-яa-z0-9-]*/g) || [])]
    .filter((w) => w.length >= 4 && !FREE_STOP.test(w) && !known.some((re) => re.test(w)) && !cities.some((c) => w.startsWith(c)));
  return { words, stems: [...new Set(words.map(freeStem))] };
}

/* Разбор запроса по правилам: текст → продукты, материал, объём, регион, коды */
function parseQuery(text) {
  const t = " " + String(text || "").toLowerCase().replace(/ё/g, "е") + " ";
  const q = { raw: text, products: [], technologies: [], material: null, grades: [], industry: null, okpd2: null, okved: null, volume: null, unit: null, period: null, region: null, regionName: null, city: null, missing: [], engine: "rules" };
  for (const l of LEX) if (l.re.test(t)) q.products.push(l);
  for (const l of TECH_LEX) if (l.re.test(t)) q.technologies.push(l);
  for (const l of MAT_LEX) if (l.re.test(t)) { q.material = l; break; }
  for (const l of INDUSTRY_LEX) if (l.re.test(t)) { q.industry = l; break; }
  const grades = (text || "").match(/(?<![0-9A-Za-zА-Яа-яЁё])\d{1,2}[ХГНМТЮСФКВРА]+[0-9ХГНМТЮСФКВРА]*(?![0-9A-Za-zА-Яа-яЁё])/g); if (grades) q.grades = grades;
  const vm = t.match(/(\d[\d\s]*[.,]?\d*)\s*(тонн[а-яё]*|тн|т|кг|килограмм[а-яё]*|шт|штук[а-яё]*|единиц[а-яё]*|м2|м²|м3|м³|метр[а-яё]*|м|литр[а-яё]*|л|комплект[а-яё]*|компл|парти[а-яё]*)(?=[\s.,;/]|$)/);
  if (vm) {
    q.volume = Number(vm[1].replace(/\s/g, "").replace(",", "."));
    const u = vm[2]; for (const [re, n] of UNIT_MAP) if (re.test(u)) { q.unit = n; break; }
  }
  if (/в месяц|\/мес|ежемесячн/.test(t)) q.period = "мес"; else if (/в год|\/год|ежегодн/.test(t)) q.period = "год";
  for (const r of REGION_LEX) if (r.re.test(t)) { q.region = r.region; q.regionName = App.data.regions[r.region]?.name || r.name; break; }
  for (const c of Object.keys(App.data.cities)) if (t.includes(c.toLowerCase().slice(0, 6))) { q.city = c; break; }
  if (!q.products.length && !q.technologies.length) {
    const fw = freeWords(t);
    if (fw.stems.length) q.products.push({ label: fw.words.join(" "), stems: fw.stems, free: true });
  }
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

// Поиск основы слова в тексте (без учёта регистра и «ё»); выражение для основы собирается один раз — в каталоге тысячи позиций
const _stemRe = new Map();
const stemRe = (st) => { let re = _stemRe.get(st); if (!re) _stemRe.set(st, (re = new RegExp("(?<![а-яa-z])" + st.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))); return re; };
const hasStem = (s, stems) => { const x = String(s || "").toLowerCase().replace(/ё/g, "е"); return stems.some((st) => stemRe(st).test(x)); };
// Текст позиции для поиска строчными: полный (название, категория, описание) и краткий (название, категория) — один раз на позицию
const _ptext = new WeakMap();
const prodText = (p) => {
  let t = _ptext.get(p);
  if (!t) { const short = (p.name + " " + (p.category || "")).toLowerCase().replace(/ё/g, "е"); _ptext.set(p, (t = { short, full: short + " " + String(p.description || "").toLowerCase().replace(/ё/g, "е") })); }
  return t;
};

/* Сопоставление одного предприятия с запросом. Возвращает критерии с результатом и основанием. */
function matchCompany(q, c, opts = {}) {
  const crit = [];
  const prods = c.products.filter((p) => srcActive(p.source_id));
  const stems = q.products.flatMap((p) => p.stems);
  const tstems = q.technologies.flatMap((p) => p.stems);
  // PRODUCT_MATCH
  let prodHits = [];
  const free = q.products.find((p) => p.free);
  if (free) {
    // слова вне словаря: позиция подходит, если в названии или категории есть достаточно слов запроса; все слова — «совпадает»
    const res = free.stems.map(stemRe), need = freeRequired(res.length);
    const scored = prods.map((p, i) => { const x = prodText(p).short; return { p, i, n: res.filter((r) => r.test(x)).length }; })
      .sort((a, b) => b.n - a.n || a.i - b.i);
    prodHits = scored.filter((s) => s.n >= need).map((s) => s.p);
    const full = scored.length > 0 && scored[0].n === res.length;
    crit.push({ k: "PRODUCT_MATCH", n: "Продукция", r: full ? "yes" : prodHits.length ? "compat" : "no",
      why: prodHits.length ? prodHits.slice(0, 3).map((p) => esc(p.name)).join("; ") : "Нет совпадений в подтверждённой продукции", src: prodHits[0]?.source_id, prods: prodHits });
  } else if (stems.length) {
    prodHits = prods.filter((p) => { const x = prodText(p).full; return stems.some((st) => stemRe(st).test(x)); });
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
      why: srcHit ? (srcHit.okpd2.status === "COMPANY" ? "Код подтвердило предприятие" : "Код указан в источнике") : hits.length ? "Совпадает по коду, присвоенному по классификатору — требует подтверждения" : "У продукции нет подходящего кода ОКПД2 в базе" });
    if (!prodHits.length && hits.length) prodHits = hits;
  }
  // OKVED
  if (q.okved) {
    if (!c.okved_main) crit.push({ k: "OKVED", n: "ОКВЭД " + q.okved, r: "none", why: "ОКВЭД предприятия не подтверждён" });
    else if (c.okved_main === q.okved || c.okved_main.startsWith(q.okved + ".")) crit.push({ k: "EXACT_OKVED_MATCH", n: "ОКВЭД " + q.okved, r: "yes", why: "Основной ОКВЭД " + c.okved_main + " (ЕГРЮЛ)", src: egrulSrc(c)?.id });
    else if (c.okved_main.split(".")[0] === q.okved.split(".")[0]) crit.push({ k: "COMPATIBLE_OKVED", n: "ОКВЭД " + q.okved, r: "compat", why: "Основной ОКВЭД " + c.okved_main + " — тот же класс " + q.okved.split(".")[0], src: egrulSrc(c)?.id });
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
    // заявленная в ЕГРЮЛ возможность — только «совместимо», не подтверждение
    const cap = !hit && (c.capabilities_declared || []).find((x) => hasStem(x.name, tstems));
    crit.push({ k: "TECHNOLOGY_MATCH", n: "Технология: " + q.technologies.map((t) => t.label).join(", "), r: hit ? "yes" : cap ? "compat" : c.technologies.length ? "no" : "none",
      why: hit ? esc(hit.name) : cap ? `По ОКВЭД ${esc(cap.okved.join(", "))}: ${esc(cap.name)} (заявлено, не подтверждено)` : c.technologies.length ? "Указаны другие технологии" : "Технологии в открытых источниках не указаны", src: hit?.source_id || (cap ? c.registry?.source_ids?.pb : undefined) });
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

/* Поиск по всей базе: сопоставление каждого предприятия и сортировка по совпадениям */
function searchCompanies(q, { includeUnverified = false, city = App.profile.city, exclude = [] } = {}) {
  return App.data.companies
    .filter((c) => !exclude.includes(c.id))
    .filter((c) => includeUnverified || c.verification_status === "VERIFIED" || c.verification_status === "PARTIALLY_VERIFIED")
    .map((c) => matchCompany(q, c, { city }))
    .filter((m) => m.substantive)
    .sort((a, b) => b.yes - a.yes || (a.dist ?? 1e9) - (b.dist ?? 1e9));
}

/* ---- Представление результата сопоставления ---- */
function verdictSummary(m) {
  const miss = m.crit.filter((x) => x.r === "none" || x.r === "part").length;
  if (m.crit.some((x) => x.r === "no")) return "Предприятие соответствует части критериев. Несовпадения отмечены ✕.";
  if (miss) return "Соответствует указанным критериям в пределах опубликованных данных; часть параметров требует подтверждения у поставщика.";
  return "Соответствует всем указанным критериям по данным источников. Условия поставки подтверждает предприятие.";
}
const V_TXT = { yes: "Совпадает", compat: "Совместимо", part: "Требует подтверждения", none: "Нет открытых данных", no: "Не совпадает", skip: "Не задано" };
function matchTable(m) {
  return `<div class="tbl-wrap"><table class="tbl"><thead><tr><th>Критерий</th><th>Результат</th><th>Основание</th></tr></thead><tbody>
  ${m.crit.map((x) => `<tr><td title="${esc(x.k)}">${esc(x.n)}</td><td><span class="v ${x.r}">${V_TXT[x.r]}</span></td><td>${x.why} ${srcBtn(x.src)}</td></tr>`).join("")}
  </tbody></table></div>
  <div class="summary"><span class="score">${m.yes} из ${m.applicable}</span> критериев подтверждены источниками. ${verdictSummary(m)}</div>`;
}
// Чипы распознанных параметров запроса
function queryChips(q) {
  // подписи те же, что в панели «Параметры поиска»
  const out = queryParams(q).map(([k, v]) => `<span class="chip"><b>${esc(k)}</b>${esc(k === "ОКПД2" ? v + " " + (App.data.okpd2[v] || "") : v)}</span>`);
  q.missing.forEach((m) => out.push(`<span class="chip miss"><b>Не указано</b>${esc(m.t)}</span>`));
  return `<div class="chips"><span class="label">${q.engine === "claude" ? "Распознано AI (Claude) из запроса:" : "Распознано из запроса:"}</span>${out.join("")}</div>`;
}
