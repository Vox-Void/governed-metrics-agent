"""Build a dbt candidate and publish only complete, tested snapshot revisions."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import suppress
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[2]
DEMO_CLOCK = datetime.fromisoformat("2026-11-05T08:00:00+00:00")
VARIANTS = ("fresh", "stale-refunds")
INPUTS = ("captures", "refunds", "attempts")


class SnapshotError(RuntimeError):
    pass


def revision_digest(project_root: Path, variant: str, marks: object) -> str:
    """Hash the build inputs and the watermark values for one snapshot variant."""
    paths = sorted(
        [
            *project_root.glob("data/seeds/*.csv"),
            *project_root.glob("dbt_project/**/*.sql"),
            *project_root.glob("dbt_project/**/*.yml"),
            project_root / "uv.lock",
        ]
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(project_root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    digest.update(json.dumps([variant, marks], sort_keys=True).encode())
    return digest.hexdigest()[:32]


def run_dbt(project_root: Path, candidate: Path, scratch: Path) -> dict[str, int]:
    """Run the seed and build commands against a temporary DuckDB file."""
    exe = Path(sys.executable).with_name("dbt.exe" if os.name == "nt" else "dbt")
    project = project_root / "dbt_project"
    environment = {
        **os.environ,
        "GOVERNED_METRICS_BUILD_DB": str(candidate),
        "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
        "DBT_USE_COLORS": "false",
    }
    options = [
        "--project-dir",
        str(project),
        "--profiles-dir",
        str(project),
        "--target-path",
        str(scratch / "target"),
        "--log-path",
        str(scratch / "logs"),
    ]
    for args in (["seed", "--full-refresh"], ["build", "--exclude", "resource_type:seed"]):
        result = subprocess.run(
            [str(exe), *args, *options],
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=100,
            check=False,
        )
        if result.returncode:
            raise SnapshotError(
                f"dbt {args[0]} failed.\n{result.stdout[-8000:]}{result.stderr[-2400:]}"
            )
    actual = json.loads((scratch / "target/run_results.json").read_bytes())["results"]
    return {
        "models": sum(row["unique_id"].startswith("model.") for row in actual),
        "tests": sum(
            row["unique_id"].startswith("test.") and row["status"] == "pass" for row in actual
        ),
    }


def publish_snapshots(output: Path, project_root: Path = ROOT) -> dict[str, Any]:
    output = output.resolve()
    versions = output / "snapshots"
    versions.mkdir(parents=True, exist_ok=True)
    watermarks = json.loads((project_root / "data/freshness.json").read_bytes())
    revisions = {
        variant: revision_digest(project_root, variant, watermarks[variant]) for variant in VARIANTS
    }
    with TemporaryDirectory(prefix="building-", dir=output) as temp:
        scratch = Path(temp)
        candidate = scratch / "tested.duckdb"
        # Build the facts once and check the counts reported by dbt.
        checks = run_dbt(project_root, candidate, scratch)
        if checks["models"] != 6 or checks["tests"] != 7:
            raise SnapshotError("The dbt candidate did not run all six models and seven tests.")
        for variant, revision in revisions.items():
            staged = scratch / f"{revision}.duckdb"
            # Copy the facts and write this variant's revision and input watermarks.
            shutil.copyfile(candidate, staged)
            with duckdb.connect(str(staged)) as database:
                database.execute("CREATE TABLE snapshot_meta (revision VARCHAR, tested BOOLEAN)")
                database.execute("INSERT INTO snapshot_meta VALUES (?, TRUE)", [revision])
                database.execute(
                    "CREATE TABLE input_watermarks (input VARCHAR PRIMARY KEY, loaded_at TIMESTAMPTZ, complete_through DATE)"
                )
                for source, [loaded, complete] in watermarks[variant].items():
                    database.execute(
                        "INSERT INTO input_watermarks VALUES (?, ?, ?)",
                        [source, datetime.fromisoformat(loaded), date.fromisoformat(complete)],
                    )
                database.execute("CHECKPOINT")
            # Link the completed file under its revision name and keep any existing copy.
            with suppress(FileExistsError):
                os.link(staged, versions / staged.name)
        # Publish the variant-to-revision map after both files are in place.
        with NamedTemporaryFile("w", encoding="utf-8", dir=scratch, delete=False) as pointer:
            json.dump(revisions, pointer, indent=2)
            pointer.write("\n")
            pointer.flush()
            os.fsync(pointer.fileno())
        os.chmod(pointer.name, 0o644)
        os.replace(pointer.name, output / "current.json")
    return {"versions": revisions, "dbt": checks, "duckdb": duckdb.__version__}


def pin_snapshot(output: Path, variant: str) -> tuple[str, Path]:
    """Read the current map and resolve one revision to an absolute DuckDB path."""
    if variant not in VARIANTS:
        raise SnapshotError("Unknown snapshot variant.")
    try:
        revision = json.loads((output / "current.json").read_bytes())[variant]
        if not re.fullmatch(r"[0-9a-f]{32}", revision):
            raise ValueError("Invalid revision.")
        file = (output / "snapshots" / f"{revision}.duckdb").resolve()
        if not file.is_file():
            raise FileNotFoundError(file)
    except (OSError, ValueError, TypeError, KeyError) as error:
        raise SnapshotError(
            "The tested snapshot is unavailable. Run ./scripts/dev bootstrap."
        ) from error
    return revision, file
