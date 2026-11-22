import json
import subprocess
import sys

import pytest

from governed_metrics.mcp import CLIENT_CAPABILITIES_KEY, LEGACY, MODERN, VERSION_KEY
from governed_metrics.snapshots import ROOT


@pytest.mark.parametrize("version", [LEGACY, MODERN])
def test_stdio_client_uses_the_same_metric_and_scope_policy(snapshot_root, monkeypatch, version):
    monkeypatch.setenv("PYTHONPATH", str(ROOT / "src"))
    meta = (
        {} if version == LEGACY else {"_meta": {VERSION_KEY: MODERN, CLIENT_CAPABILITIES_KEY: {}}}
    )
    metric = {
        "metric_id": "net_collected",
        "merchant": "a",
        "currency": "ZAR",
        "start": "2026-11-01",
        "end": "2026-11-03",
        "grouping": "total",
        "provider": None,
    }
    requests = [
        ("initialize", {"protocolVersion": LEGACY})
        if version == LEGACY
        else ("server/discover", meta),
        ("ping", meta),
        ("tools/list", meta),
        ("tools/call", {"name": "run_metric", "arguments": metric, **meta}),
        ("tools/call", {"name": "run_metric", "arguments": {**metric, "merchant": "b"}, **meta}),
        (
            "tools/call",
            {"name": "run_metric", "arguments": {**metric, "merchant": "unknown"}, **meta},
        ),
        ("ping", {"_meta": {VERSION_KEY: "1900-01-01", CLIENT_CAPABILITIES_KEY: {}}}),
        ("ping", {"_meta": {VERSION_KEY: MODERN}}),
    ]
    lines = [
        json.dumps({"jsonrpc": "2.0", "id": index, "method": method, "params": arguments})
        for index, (method, arguments) in enumerate(requests)
    ]
    process = subprocess.run(
        [sys.executable, "-m", "governed_metrics.cli", "mcp", "--root", str(snapshot_root)],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    )
    replies = [json.loads(line) for line in process.stdout.splitlines()]
    boot, ping, tools, success, blocked, unknown = [item["result"] for item in replies[:-2]]
    assert (
        boot["protocolVersion"] == version
        if version == LEGACY
        else version in boot["supportedVersions"]
    )
    if version == MODERN:
        assert all(item["resultType"] == "complete" for item in (boot, ping, tools))
        assert all((item["ttlMs"], item["cacheScope"]) == (0, "private") for item in (boot, tools))
    else:
        assert all({"ttlMs", "cacheScope"}.isdisjoint(item) for item in (boot, tools))
    assert replies[-2]["error"]["code"] == -32022
    assert replies[-2]["error"]["data"] == {
        "requested": "1900-01-01",
        "supported": [MODERN, LEGACY],
    }
    assert replies[-1]["error"]["code"] == -32602
    assert [tool["name"] for tool in tools["tools"]] == ["list_metrics", "run_metric"]
    assert success["structuredContent"]["rows"][0]["value"] == 13000
    for item in (blocked, unknown):
        assert item["structuredContent"]["status"] == "denied"
        assert set(item["structuredContent"]) == {"status", "reason", "trace_id"}
