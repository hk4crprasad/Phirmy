"""Apply the reviewed additive beta schema with a migration-role connection.

Take a backup first. The production API only verifies this schema and does not
perform DDL. This command never drops application tables or modifies .env.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/control'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Read-only schema readiness check')
    args = parser.parse_args()
    try:
        from studio.main import initialize_database, verify_database_schema, SCHEMA_REVISION
        if args.check:
            verify_database_schema()
        else:
            initialize_database()
            verify_database_schema()
        print('Schema ready:', SCHEMA_REVISION)
    except Exception as exc:
        print('Schema operation failed:', type(exc).__name__)
        print('Check the database route, migration role and backup; connection details are intentionally omitted.')
        raise SystemExit(1)

if __name__ == '__main__':
    main()
