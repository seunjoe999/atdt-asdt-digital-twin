"""Verifies a Render Postgres backup restore actually worked.

Render's dashboard can restore a backup snapshot to a brand-new scratch
Postgres instance (Postgres service -> Backups tab -> pick a snapshot ->
"Restore to new database"). That UI flow tests that the backup *exists*;
this script tests that the backup is *correct* -- it connects to the live
production database and the freshly-restored scratch database and diffs
row counts (and a cheap content checksum) per table, table by table.

Usage:
    python scripts/verify_backup_restore.py <production_url> <restored_scratch_url>

Both URLs are Render's "External Database URL" for each instance (found on
each Postgres service's Info page) -- NOT the internal URL, since this runs
from outside Render's network. Never commit these URLs or paste them
anywhere that persists; pass them as CLI args from a shell that doesn't log
history, or as env vars.

Exit code 0 = every table matches. Exit code 1 = a mismatch was found (the
restore is missing or has different data from production) -- treat that as
a real incident, not a script bug, and re-run the restore before trusting
the backup.
"""

from __future__ import annotations

import hashlib
import sys

from sqlalchemy import create_engine, inspect, text

TABLES = [
    "users",
    "courses",
    "enrollments",
    "documents",
    "teaching_materials",
    "teaching_style_profiles",
    "conversations",
    "messages",
    "course_messages",
    "assessments",
    "questions",
    "attempts",
    "responses",
    "wellbeing_checkins",
    "streak_states",
    "counseling_messages",
]


def _normalize(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def _table_fingerprint(engine, table: str) -> tuple[int, str] | None:
    """(row_count, checksum) for one table, or None if the table doesn't exist."""
    with engine.connect() as conn:
        existing = set(inspect(conn).get_table_names())
        if table not in existing:
            return None
        count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        # Order-independent content checksum: hash every row's text
        # representation, XOR the hashes together so row order (which a
        # restore is not guaranteed to preserve) can't cause a false mismatch.
        rows = conn.execute(text(f"SELECT * FROM {table}")).fetchall()
        acc = 0
        for row in rows:
            row_hash = hashlib.sha256(repr(tuple(row)).encode()).digest()
            acc ^= int.from_bytes(row_hash, "big")
        return count, format(acc, "x")


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2

    prod_url, restored_url = (_normalize(u) for u in sys.argv[1:3])
    prod = create_engine(prod_url)
    restored = create_engine(restored_url)

    print(f"{'table':<24} {'prod rows':>10} {'restored rows':>14}  match?")
    print("-" * 60)

    all_ok = True
    for table in TABLES:
        prod_fp = _table_fingerprint(prod, table)
        restored_fp = _table_fingerprint(restored, table)

        if prod_fp is None:
            print(f"{table:<24} {'(no table)':>10}")
            continue

        prod_count, prod_hash = prod_fp
        if restored_fp is None:
            print(f"{table:<24} {prod_count:>10} {'MISSING':>14}  FAIL")
            all_ok = False
            continue

        restored_count, restored_hash = restored_fp
        ok = prod_count == restored_count and prod_hash == restored_hash
        all_ok &= ok
        print(f"{table:<24} {prod_count:>10} {restored_count:>14}  {'ok' if ok else 'FAIL'}")

    print("-" * 60)
    print("RESTORE VERIFIED — every table matches." if all_ok else "RESTORE MISMATCH — see FAIL rows above.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
