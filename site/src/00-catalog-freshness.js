/* Проверка возраста серверного каталога и безопасная загрузка резервного снимка. */
"use strict";

const CATALOG_MAX_AGE_MS = 48 * 60 * 60 * 1000;
const CATALOG_CLOCK_SKEW_MS = 5 * 60 * 1000;

function catalogTimestampMs(value) {
  if (typeof value !== "string" || !value.trim()) return null;
  let timestamp = value.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(timestamp)) timestamp += "T00:00:00";
  // Синхронизация хранится в часовом поясе сервера (Europe/Volgograd, UTC+03:00).
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(timestamp)) timestamp += "+03:00";
  const parsed = Date.parse(timestamp);
  return Number.isFinite(parsed) ? parsed : null;
}

function inspectCatalogFreshness(bundleOrTimestamp, nowMs = Date.now()) {
  const sourceUpdatedAt =
    typeof bundleOrTimestamp === "string"
      ? bundleOrTimestamp
      : bundleOrTimestamp?.sync?.finished;
  const updatedAtMs = catalogTimestampMs(sourceUpdatedAt);
  if (updatedAtMs === null) {
    return { status: "unknown", sourceUpdatedAt: sourceUpdatedAt || null, ageMs: null };
  }

  const ageMs = nowMs - updatedAtMs;
  if (ageMs < -CATALOG_CLOCK_SKEW_MS) {
    return { status: "unknown", sourceUpdatedAt, ageMs, reason: "future_timestamp" };
  }
  return {
    status: ageMs <= CATALOG_MAX_AGE_MS ? "fresh" : "stale",
    sourceUpdatedAt,
    ageMs: Math.max(0, ageMs),
  };
}

function isCatalogRollback(next, current, nextETag = null, currentETag = null) {
  if (!next || !current) return false;
  const nextRevision = Number(next.revision);
  const currentRevision = Number(current.revision);
  if (
    Number.isFinite(nextRevision) &&
    Number.isFinite(currentRevision) &&
    nextRevision < currentRevision
  ) {
    return true;
  }
  const nextTimestamp = catalogTimestampMs(next.sync?.finished);
  const currentTimestamp = catalogTimestampMs(current.sync?.finished);
  if (nextTimestamp !== null && currentTimestamp !== null && nextTimestamp < currentTimestamp)
    return true;

  const etagParts = (etag) => {
    const match = /^W\/"cat-(\d+)-fin(\d+)-(\d+)-(\d+)"$/.exec(etag || "");
    return match ? match.slice(1).map(Number) : null;
  };
  const nextVersion = etagParts(nextETag);
  const currentVersion = etagParts(currentETag);
  if (!nextVersion || !currentVersion) return false;
  for (let i = 0; i < nextVersion.length; i++) {
    if (nextVersion[i] !== currentVersion[i]) return nextVersion[i] < currentVersion[i];
  }
  return false;
}

function catalogLoadError(message, code, extra = {}) {
  return Object.assign(new Error(message), { code, ...extra });
}

function requireFreshCatalog(data) {
  const freshness = inspectCatalogFreshness(data);
  if (freshness.status !== "fresh") {
    throw catalogLoadError("Срок актуальности каталога не подтверждён.", "CATALOG_NOT_FRESH", {
      freshness,
    });
  }
  return freshness;
}

/** Загружает свежий каталог; снимок разрешён только для автономного режима или сетевого сбоя. */
async function loadCatalogSnapshot(fetchImpl = fetch, currentETag = null, currentData = null) {
  let apiResponse;
  let networkUnavailable = false;
  try {
    apiResponse = await fetchImpl("/api/v1/bundle", { cache: "no-cache" });
  } catch (error) {
    networkUnavailable = true;
  }

  if (!networkUnavailable) {
    const etag = apiResponse.headers?.get?.("ETag") || null;
    const sameVersion = etag && etag === currentETag && currentData;
    if (apiResponse.status === 304 && sameVersion) {
      const freshness = requireFreshCatalog(currentData);
      return { data: currentData, freshness, source: "api", etag, unchanged: true };
    }
    if (apiResponse.status === 304) {
      throw catalogLoadError(
        "Сервер подтвердил каталог без тела ответа, но его локальная версия не совпадает.",
        "CATALOG_VERSION_MISMATCH",
        { etag }
      );
    }
    if (apiResponse.ok && sameVersion) {
      const freshness = requireFreshCatalog(currentData);
      return { data: currentData, freshness, source: "api", etag, unchanged: true };
    }
  }

  if (!networkUnavailable && apiResponse.ok) {
    const data = await apiResponse.json();
    const freshness = requireFreshCatalog(data);
    return {
      data,
      freshness,
      source: "api",
      etag: apiResponse.headers?.get?.("ETag") || null,
      unchanged: false,
    };
  }

  if (!networkUnavailable && apiResponse.status !== 404) {
    throw catalogLoadError(
      `Сервер каталога вернул HTTP ${apiResponse.status}.`,
      "CATALOG_API_ERROR",
      { status: apiResponse.status }
    );
  }

  let snapshotResponse;
  try {
    snapshotResponse = await fetchImpl("data.json", {
      cache: networkUnavailable ? "force-cache" : "no-cache",
    });
  } catch (error) {
    throw catalogLoadError("Резервный снимок каталога недоступен.", "CATALOG_SNAPSHOT_ERROR");
  }
  if (!snapshotResponse.ok) {
    throw catalogLoadError(
      `Резервный снимок каталога вернул HTTP ${snapshotResponse.status}.`,
      "CATALOG_SNAPSHOT_ERROR",
      { status: snapshotResponse.status }
    );
  }

  const data = await snapshotResponse.json();
  const freshness = requireFreshCatalog(data);
  return { data, freshness, source: "snapshot" };
}
