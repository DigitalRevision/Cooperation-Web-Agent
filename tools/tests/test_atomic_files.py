from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.atomic_files import atomic_write
from tools.export_bundle import publish_bundle


def test_atomic_write_preserves_previous_file_after_writer_failure(tmp_path: Path) -> None:
    target = tmp_path / "bundle.json"
    target.write_bytes(b"previous")

    def fail_after_partial_write(stream) -> None:
        stream.write(b"partial")
        raise RuntimeError("serialization failed")

    with pytest.raises(RuntimeError, match="serialization failed"):
        atomic_write(target, fail_after_partial_write)

    assert target.read_bytes() == b"previous"
    assert list(tmp_path.glob(".bundle.json.*.tmp")) == []


def test_publish_bundle_streams_json_and_updates_dist_atomically(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    data = {"revision": 3, "companies": [{"id": "one", "name": "Проверка"}]}

    output, size = publish_bundle(data, tmp_path)

    expected = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert output == tmp_path / "data.json"
    assert output.read_bytes() == expected
    assert (dist / "data.json").read_bytes() == expected
    assert size == len(expected)
