"""Expose two typed metrics tools over a local JSON-RPC stdio connection."""

import json
import sys
from typing import Any

from governed_metrics.auth import Principal
from governed_metrics.schemas import MetricPlan
from governed_metrics.service import Service

MODERN = "2026-07-28"
LEGACY = "2025-11-25"
SERVER = {"name": "governed-metrics-agent", "version": "0.1.0"}
CAPABILITIES = {"tools": {"listChanged": False}}
VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
CLIENT_CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"


def tool_definitions() -> list[dict[str, Any]]:
    plan_schema = MetricPlan.model_json_schema()
    # The adapter supplies the plan kind when it forwards a tool call.
    del plan_schema["properties"]["kind"]
    plan_schema["required"].remove("kind")
    return [
        {
            "name": "list_metrics",
            "description": "List the metrics and groupings granted to the launcher's profile.",
            "inputSchema": {
                "type": "object",
                "properties": {"merchant": {"type": "string"}},
                "required": ["merchant"],
                "additionalProperties": False,
            },
        },
        {
            "name": "run_metric",
            "description": "Run an approved metric with an inclusive start and exclusive end date.",
            "inputSchema": plan_schema,
        },
    ]


def rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve(service: Service, principal: Principal, variant: str) -> None:
    """Read one JSON-RPC message per line and write responses to standard output."""
    legacy_session = False
    for line in sys.stdin:
        request_id = None
        try:
            if len(line.encode()) > 16_000:
                raise ValueError("Request too large")
            document = json.loads(line)
            if not isinstance(document, dict) or document.get("jsonrpc") != "2.0":
                print(json.dumps(rpc_error(None, -32600, "Invalid request")), flush=True)
                continue
            # Dispatch requests with IDs and skip notifications.
            if "id" not in document:
                continue
            request_id = document["id"]
            method = document.get("method")
            params = document.get("params", {})
            if not isinstance(params, dict):
                raise TypeError("Invalid params")
            meta = params.get("_meta", {})
            if not isinstance(meta, dict):
                raise TypeError("Invalid request metadata")
            # Read the protocol version from this request before dispatching it.
            requested = meta.get(VERSION_KEY)
            if VERSION_KEY in meta and not isinstance(requested, str):
                raise TypeError("Protocol version must be a string")
            if requested is not None and requested != MODERN:
                error = rpc_error(request_id, -32022, "Unsupported protocol version")
                error["error"]["data"] = {"supported": [MODERN, LEGACY], "requested": requested}
                print(json.dumps(error), flush=True)
                continue
            modern = requested == MODERN
            if modern and not isinstance(meta.get(CLIENT_CAPABILITIES_KEY), dict):
                raise TypeError("Client capabilities are required")
            result: dict[str, Any]
            if method == "initialize" and not modern:
                legacy_session = True
                result = {
                    "protocolVersion": LEGACY,
                    "serverInfo": SERVER,
                    "capabilities": CAPABILITIES,
                }
            elif method == "server/discover" and modern:
                result = {"supportedVersions": [MODERN, LEGACY], "capabilities": CAPABILITIES}
            elif not (modern or legacy_session):
                raise TypeError("Protocol version is required")
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": tool_definitions()}
            elif method == "tools/call":
                name = params.get("name")
                arguments = params.get("arguments")
                if not isinstance(arguments, dict) or not isinstance(
                    arguments.get("merchant"), str
                ):
                    raise TypeError("The merchant argument must be a string")
                merchant = arguments["merchant"]
                # Forward the launcher's profile with each tool call.
                if name == "list_metrics" and set(arguments) == {"merchant"}:
                    data = service.discover(merchant, principal)
                elif name == "run_metric" and "kind" not in arguments:
                    payload = json.dumps({**arguments, "kind": "plan"})
                    data = service.structured(
                        payload, merchant, principal, variant=variant
                    ).model_dump(mode="json")
                else:
                    raise TypeError("Unknown tool or invalid arguments")
                result = {
                    "content": [{"type": "text", "text": json.dumps(data)}],
                    "structuredContent": data,
                    "isError": False,
                }
            else:
                print(json.dumps(rpc_error(request_id, -32601, "Method not found")), flush=True)
                continue
        except ValueError:
            print(json.dumps(rpc_error(request_id, -32700, "Invalid JSON")), flush=True)
            continue
        except TypeError:
            print(json.dumps(rpc_error(request_id, -32602, "Invalid parameters")), flush=True)
            continue
        if modern:
            result["_meta"] = {"io.modelcontextprotocol/serverInfo": SERVER}
            result["resultType"] = "complete"
            if method in {"server/discover", "tools/list"}:
                result.update(ttlMs=0, cacheScope="private")
        print(json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}), flush=True)
