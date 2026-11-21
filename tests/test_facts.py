import duckdb

from governed_metrics.snapshots import pin_snapshot


def test_build_keeps_composite_keys_and_uses_johannesburg_day(snapshot_root):
    revision, path = pin_snapshot(snapshot_root, "fresh")
    with duckdb.connect(str(path), read_only=True) as database:
        rows = database.execute("""
            select merchant_id, capture_id, cast(business_date as varchar), amount_minor
            from fct_captures where capture_id in ('c1', 'c4') order by merchant_id, capture_id
        """).fetchall()
        assert rows == [
            ("a", "c1", "2026-11-01", 10000),
            ("a", "c4", "2026-11-03", 15000),
            ("b", "c1", "2026-11-02", 90000),
        ]
        assert database.execute(
            "SELECT status, source_version FROM fct_attempts WHERE merchant_id = 'a' AND attempt_id = 'a1'"
        ).fetchone() == ("succeeded", 2)
        assert database.execute("SELECT revision, tested FROM snapshot_meta").fetchone() == (
            revision,
            True,
        )


def test_capture_and_refund_totals_are_independent(snapshot_root):
    _, path = pin_snapshot(snapshot_root, "fresh")
    with duckdb.connect(str(path), read_only=True) as database:
        totals = []
        for fact in ("fct_captures", "fct_refunds"):
            amount = database.execute(f"""
                select sum(amount_minor) from {fact} where merchant_id = 'a' and currency = 'ZAR'
                    and status = 'settled' and business_date >= '2026-11-01' and business_date < '2026-11-03'
            """).fetchone()
            totals.append(amount[0])
        assert totals == [17000, 4000]
