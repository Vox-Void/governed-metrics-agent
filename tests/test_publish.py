import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from governed_metrics import snapshots
from governed_metrics.auth import PROFILES
from governed_metrics.planner import ScriptedPlanner
from governed_metrics.service import Service


def isolated_project(tmp_path):
    project = tmp_path / "fixture-project"
    project.mkdir()
    for directory in ("data", "dbt_project"):
        shutil.copytree(snapshots.ROOT / directory, project / directory)
    shutil.copyfile(snapshots.ROOT / "uv.lock", project / "uv.lock")
    return project


def answer(path):
    return Service(path).ask(
        "Captured amount in ZAR on 3 November 2026", "a", PROFILES["analyst-a"], ScriptedPlanner()
    )


def test_conflicting_same_version_fails_dbt_and_keeps_last_good_snapshot(snapshot_root, tmp_path):
    local = shutil.copytree(snapshot_root, tmp_path / "publish")
    before = snapshots.pin_snapshot(local, "fresh")[0]
    project = isolated_project(tmp_path)
    seed = project / "data/seeds/capture_deliveries.csv"
    # Submit a different amount under the same capture ID and source version.
    with seed.open("a", encoding="utf-8", newline="") as stream:
        stream.write(
            "a,c1,o1,a1,CARD,ZAR,settled,2026-10-31T22:10:00Z,11000,1,2026-11-05T07:49:00Z\n"
        )
    with pytest.raises(snapshots.SnapshotError, match="no_conflicting_versions"):
        snapshots.publish_snapshots(local, project)
    assert snapshots.pin_snapshot(local, "fresh")[0] == before
    assert answer(local).rows[0].value == 15000


@pytest.mark.parametrize("replacement", [b",-0.1,1,", b",15000,1.1,"])
def test_fractional_amount_or_version_cannot_be_certified(snapshot_root, tmp_path, replacement):
    local = shutil.copytree(snapshot_root, tmp_path / "publish")
    before = snapshots.pin_snapshot(local, "fresh")[0]
    project = isolated_project(tmp_path)
    seed = project / "data/seeds/capture_deliveries.csv"
    seed.write_bytes(seed.read_bytes().replace(b",15000,1,", replacement))

    with pytest.raises(snapshots.SnapshotError, match="valid_delivery_values"):
        snapshots.publish_snapshots(local, project)
    assert snapshots.pin_snapshot(local, "fresh")[0] == before
    assert answer(local).rows[0].value == 15000


def test_concurrent_read_sees_one_complete_revision(snapshot_root, tmp_path, monkeypatch):
    local = shutil.copytree(snapshot_root, tmp_path / "publish")
    before = snapshots.pin_snapshot(local, "fresh")[0]
    project = isolated_project(tmp_path)
    seed = project / "data/seeds/capture_deliveries.csv"
    seed.write_bytes(seed.read_bytes().replace(b",15000,1,", b",15200,1,"))
    built = Event()
    publish = Event()
    real_dbt = snapshots.run_dbt

    def staged(*arguments):
        # Pause after dbt passes and before the published pointer changes.
        checks = real_dbt(*arguments)
        built.set()
        assert publish.wait(15), "Expected the parallel read to finish before publication"
        return checks

    monkeypatch.setattr(snapshots, "run_dbt", staged)
    with ThreadPoolExecutor(max_workers=1) as thread:
        job = thread.submit(snapshots.publish_snapshots, local, project)
        try:
            assert built.wait(30), "The dbt candidate did not reach the publish boundary"
            old = answer(local)
            assert old.snapshot_id == before and old.rows[0].value == 15000
        finally:
            publish.set()
        complete = job.result(timeout=15)["versions"]["fresh"]
    new = answer(local)
    assert new.snapshot_id == complete != before
    assert new.rows[0].value == 15200


def test_revision_and_dbt_build_use_the_same_copied_inputs(tmp_path, monkeypatch):
    project = isolated_project(tmp_path)
    output = tmp_path / "published"
    marks = json.loads((project / "data/freshness.json").read_bytes())["fresh"]
    expected_revision = snapshots.revision_digest(project, "fresh", marks)
    seed = project / "data/seeds/capture_deliveries.csv"
    real_dbt = snapshots.run_dbt

    def build_after_source_edit(build_root, candidate, scratch):
        seed.write_bytes(seed.read_bytes().replace(b",15000,1,", b",15200,1,"))
        return real_dbt(build_root, candidate, scratch)

    monkeypatch.setattr(snapshots, "run_dbt", build_after_source_edit)
    snapshots.publish_snapshots(output, project)
    response = answer(output)

    assert response.snapshot_id == expected_revision
    assert snapshots.revision_digest(project, "fresh", marks) != expected_revision
    assert response.rows[0].value == 15000


def test_numeric_looking_order_ids_are_distinct(tmp_path):
    project = isolated_project(tmp_path)
    output = tmp_path / "published"
    # Make all order IDs look numeric, including two distinct IDs with the same numeric value.
    for source in ("capture_deliveries", "attempt_deliveries"):
        seed = project / f"data/seeds/{source}.csv"
        numbered = seed.read_bytes()
        order_ids = (b"20", b"01", b"1", b"23", b"24", b"25", b"26")
        for ordinal, order_id in enumerate(order_ids):
            numbered = numbered.replace(f",o{ordinal},".encode(), b"," + order_id + b",")
        seed.write_bytes(numbered)
    snapshots.publish_snapshots(output, project)
    response = Service(output).ask(
        "Paying orders in ZAR on 1-2 November 2026", "a", PROFILES["analyst-a"], ScriptedPlanner()
    )

    assert response.status == "ok"
    assert response.rows[0].value == 2


def test_publish_refuses_a_damaged_existing_revision(snapshot_root, tmp_path):
    output = shutil.copytree(snapshot_root, tmp_path / "published")
    revision, database = snapshots.pin_snapshot(output, "fresh")
    pointer = output / "current.json"
    before = pointer.read_bytes()
    database.write_bytes(b"not a DuckDB file")

    with pytest.raises(
        snapshots.SnapshotError, match=f"Existing snapshot {revision} could not be read"
    ):
        snapshots.publish_snapshots(output)

    assert pointer.read_bytes() == before
