"""The quickstart in the package docstring runs against the 0.5.0 API."""

from __future__ import annotations

import json
import re

import respx

import kloakd
from tests.conftest import ORG_PREFIX, TEST_BASE_URL, mock_response

BASE = f"{TEST_BASE_URL}{ORG_PREFIX}"


@respx.mock
def test_the_quickstart_runs(capsys: object) -> None:
    respx.post(f"{BASE}/evadr/fetch").mock(return_value=mock_response({"success": True, "url": "https://books.toscrape.com", "status_code": 200, "tier_used": 1, "artifact": {"artifact_id": "art-1"}}))
    extract = respx.post(f"{BASE}/kolektr/extract").mock(return_value=mock_response({"success": True, "records": [{"title": "A", "price": "£1"}], "total_records": 1}))
    code = re.search(r"Quickstart::\n(.*?)\nRequests that run long", kloakd.__doc__ or "", re.S).group(1)
    code = "\n".join(line[4:] for line in code.splitlines())
    code = code.replace('"sk-live-..."', '"sk-test-k"').replace('"your-org-id"', f'"{ORG_PREFIX.rsplit("/", 1)[1]}"').replace("Kloakd(", f'Kloakd(base_url="{TEST_BASE_URL}", ', 1)
    exec(compile(code, "kloakd.__doc__", "exec"), {})
    body = json.loads(extract.calls.last.request.content)
    assert body["fetch_artifact_id"] == "art-1"
    assert body["schema_spec"]["fields"][0] == {"name": "title", "selector": "h3 a"}
