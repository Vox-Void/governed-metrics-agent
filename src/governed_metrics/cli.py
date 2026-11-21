"""Build and inspect the certified payments fixture."""

import argparse
import json
from pathlib import Path

from governed_metrics.snapshots import SnapshotError, publish_snapshots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap",))
    parser.add_argument("--out", type=Path, default=Path("artifacts"))
    args = parser.parse_args()
    try:
        metadata = publish_snapshots(args.out)
    except SnapshotError as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(metadata, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
