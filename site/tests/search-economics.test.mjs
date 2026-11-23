import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../src/02-match.js", import.meta.url), "utf8");
const context = vm.createContext({
  App: { data: { okved: {} }, profile: {} },
  srcActive: () => true,
  esc: (value) => String(value ?? ""),
  egrulSrc: () => ({ id: "egrul" }),
});
vm.runInContext(source, context);

const query = { products: [], technologies: [], okved: "28.15", grades: [] };
function company(overrides = {}) {
  return {
    products: [],
    okved_main: null,
    okved_extra: [],
    sources: [],
    business_scale: { category: "unknown" },
    financial_years: [],
    has_confirmed_financial_data: false,
    ...overrides,
  };
}

test("confirmed revenue OKVED ranks above declared, official main, and additional OKVED", () => {
  const rows = [
    company({ leading_financial_activity: { okved_code: "28.15", status: "CONFIRMED" } }),
    company({ leading_financial_activity: { okved_code: "28.15", status: "DECLARED" } }),
    company({ okved_main: "28.15" }),
    company({ okved_extra: ["28.15"] }),
  ].map((c) => context.matchCompany(query, c));

  assert.deepEqual(
    rows.map((x) => x.matchWeight),
    [100, 80, 50, 30]
  );
  assert.deepEqual(
    rows.map((x) => x.crit[0].k),
    [
      "LEADING_REVENUE_OKVED",
      "LEADING_REVENUE_OKVED",
      "EXACT_OKVED_MATCH",
      "ADDITIONAL_OKVED_MATCH",
    ]
  );
});

test("scale, official and revenue OKVED, year, and confirmed-finance filters are applied independently", () => {
  const c = company({
    business_scale: { category: "medium", status: "OFFICIAL" },
    okved_main: "28.15",
    leading_financial_activity: { okved_code: "46.69", status: "CONFIRMED" },
    financial_years: [2025, 2024],
    has_confirmed_financial_data: true,
  });
  assert.equal(
    context.matchesEconomicFilters(c, {
      scale: "medium",
      mainOkved: "28.15",
      revenueOkved: "46.69",
      financialYear: "2025",
      confirmedFinance: true,
    }),
    true
  );
  assert.equal(context.matchesEconomicFilters(c, { scale: "large" }), false);
  assert.equal(context.matchesEconomicFilters(c, { mainOkved: "46.69" }), false);
  assert.equal(context.matchesEconomicFilters(c, { revenueOkved: "28.15" }), false);
  assert.equal(context.matchesEconomicFilters(c, { financialYear: "2023" }), false);
  assert.equal(
    context.matchesEconomicFilters(
      { ...c, has_confirmed_financial_data: false },
      { confirmedFinance: true }
    ),
    false
  );
  assert.equal(context.matchesEconomicFilters(company(), { scale: "unknown" }), true);
});
