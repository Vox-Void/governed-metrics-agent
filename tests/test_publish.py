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
