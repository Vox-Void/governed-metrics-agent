"""Execute one internally compiled query against a pinned, read-only snapshot."""

import json
import sys
from pathlib import Path
from typing import Any

import duckdb


def connect_read_only(
    path: Path, *, threads: int = 2, memory_mib: int = 256
) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(
        str(path),
        read_only=True,
        config={
            "threads": str(threads),
            "memory_limit": f"{memory_mib}MiB",
            "enable_external_access": "false",
            "autoinstall_known_extensions": "false",
            "autoload_known_extensions": "false",
        },
    )


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        with connect_read_only(
            Path(payload["snapshot"]), threads=payload["threads"], memory_mib=payload["memory_mib"]
        ) as connection:
            rows = connection.execute(payload["statement"], payload["parameters"]).fetchmany(61)
    except (duckdb.Error, ValueError, OSError):
        return {"status": "QUERY_FAILED"}
    if len(rows) > 60:
        return {"status": "RESULT_LIMIT"}
    return {"status": "OK", "rows": rows}


def main() -> None:
    payload = json.loads(sys.stdin.read(16_000))
    print(json.dumps(execute(payload)))


if __name__ == "__main__":
    main()
