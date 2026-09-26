"""Create a disposable database, exercise migrations, then remove only that database."""
import os
import subprocess
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.core.config import get_settings


def main():
    url = make_url(get_settings().database_url.get_secret_value())
    database = "migration_test_" + uuid4().hex
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT",
                          poolclass=NullPool)
    with admin.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{database}"')
    env = dict(os.environ, DATABASE_URL=url.set(database=database).render_as_string(hide_password=False))
    try:
        for command in (
            ["alembic", "upgrade", "head"],
            ["alembic", "check"],
            ["python", "-m", "tests.check_database"],
            ["python", "-m", "tests.check_profiling"],
            ["python", "-m", "tests.check_notebooks"],
            ["alembic", "downgrade", "base"],
            ["alembic", "upgrade", "head"],
            ["python", "-m", "tests.check_database"],
        ):
            subprocess.run(command, env=env, check=True)
        print("PASS: fresh migration, schema agreement, downgrade, and re-upgrade")
    finally:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE "{database}" WITH (FORCE)')
        admin.dispose()


if __name__ == "__main__":
    main()
