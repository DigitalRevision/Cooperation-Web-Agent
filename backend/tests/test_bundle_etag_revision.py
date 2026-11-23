from __future__ import annotations

import uuid
from types import SimpleNamespace

from app import bundle
from pkdb import tx


def test_bundle_etag_changes_when_crawl_log_grows() -> None:
    repo = SimpleNamespace(revision=17, financial_revision=0)
    url = f"https://etag-test.invalid/{uuid.uuid4()}"
    before = bundle.etag_of(repo)
    try:
        with tx("ingest") as connection:
            connection.execute(
                "INSERT INTO crawl_log (day, url, status) VALUES (CURRENT_DATE, %s, 'OK')",
                (url,),
            )
        after = bundle.etag_of(repo)
        assert after != before
    finally:
        with tx("ingest") as connection:
            connection.execute("DELETE FROM crawl_log WHERE url = %s", (url,))
