import pytest

from governed_metrics.snapshots import publish_snapshots


@pytest.fixture(scope="session")
def snapshot_root(tmp_path_factory):
    path = tmp_path_factory.mktemp("certified-snapshots")
    publish_snapshots(path)
    return path
