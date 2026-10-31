"""Apply table permissions after migration, using the private migration login."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'services/control'))


def main():
    from sqlalchemy import text
    from studio.db import engine
    with engine.begin() as connection:
        if not connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname='phirmy_runtime'")).scalar():
            raise RuntimeError('Provision the runtime role before deployment')
        for statement in (
            'GRANT USAGE ON SCHEMA voice_studio TO phirmy_runtime',
            'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA voice_studio TO phirmy_runtime',
            'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA voice_studio TO phirmy_runtime',
            'REVOKE CREATE ON SCHEMA voice_studio FROM phirmy_runtime',
        ):
            connection.execute(text(statement))
    print('Runtime database grants applied.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Runtime grants failed; connection details suppressed.', file=sys.stderr)
        raise SystemExit(1)
