"""Adopt the named beta catalog for existing Free subscriptions; dry run by default."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/control'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog-version', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    from studio.beta_allowances import apply_catalog
    from studio.db import session_scope
    try:
        with session_scope(write=args.apply) as db:
            result = apply_catalog(db, expected_version=args.catalog_version, apply=args.apply)
    except Exception:
        raise SystemExit('Beta allowance adoption failed; inspect protected operator logs. No credentials printed.') from None
    print(json.dumps(result))


if __name__ == '__main__':
    main()
