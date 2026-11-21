"""Supervise the read-only DuckDB worker and enforce the wall-clock deadline."""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from governed_metrics.compiler import Statement
from governed_metrics.snapshots import ROOT


class QueryFailure(RuntimeError):
    pass


class Executor(Protocol):
    def query(self, path: Path, statement: Statement) -> list[list[Any]]: ...


@dataclass(frozen=True)
class DuckDBExecutor:
    threads: int = 2
    memory_mib: int = 256
    deadline_seconds: float = 3.0

    def query(self, path: Path, statement: Statement) -> list[list[Any]]:
        request = json.dumps(
            {
                "snapshot": str(path),
                "statement": statement.sql,
                "parameters": statement.parameters,
                "threads": self.threads,
                "memory_mib": self.memory_mib,
            }
        )
        # Pass only the listed platform environment variables and the package path to the worker.
        environment = {
            name: value
            for name, value in os.environ.items()
            if name.upper()
            in {
                "PATH",
                "SYSTEMROOT",
                "WINDIR",
                "TEMP",
                "TMP",
                "TMPDIR",
                "OS",
                "LANG",
                "LC_ALL",
                "LD_LIBRARY_PATH",
            }
        }
        environment["PYTHONPATH"] = str(ROOT / "src")
        try:
            outcome = subprocess.run(
                [sys.executable, "-m", "governed_metrics.worker"],
                cwd=ROOT,
                env=environment,
                input=request,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self.deadline_seconds,
                check=True,
            )
            payload = json.loads(outcome.stdout)
        except subprocess.TimeoutExpired as error:
            raise QueryFailure("QUERY_TIMEOUT") from error
        except (subprocess.SubprocessError, OSError, ValueError) as error:
            raise QueryFailure("WORKER_UNAVAILABLE") from error
        # Translate the worker's error status into the service's query failure codes.
        if payload.get("status") != "OK":
            reason = payload.get("status", "WORKER_UNAVAILABLE")
            raise QueryFailure(
                reason if reason in {"QUERY_FAILED", "RESULT_LIMIT"} else "WORKER_UNAVAILABLE"
            )
        rows: list[list[Any]] = payload["rows"]
        return rows
