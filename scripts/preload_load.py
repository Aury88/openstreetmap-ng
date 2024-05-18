import gc
import pathlib
import subprocess
from functools import cache
from subprocess import Popen

import anyio
from anyio import Semaphore, create_task_group
from sqlalchemy import Index, select, text

from app.config import PRELOAD_DIR
from app.db import db, db_commit, db_update_stats
from app.models.db import *  # noqa: F403
from app.models.db.changeset import Changeset
from app.models.db.element import Element
from app.models.db.element_member import ElementMember
from app.models.db.user import User
from app.services.migration_service import MigrationService

index_semaphore = Semaphore(6)

# freeze all gc objects before starting for improved performance
gc.collect()
gc.freeze()
gc.disable()


@cache
def get_csv_path(name: str) -> pathlib.Path:
    p = pathlib.Path(PRELOAD_DIR / f'{name}.csv.zst')
    if not p.is_file():
        raise FileNotFoundError(f'File not found: {p}')
    return p


@cache
def get_csv_header(path: pathlib.Path) -> str:
    with Popen(
        (  # noqa: S603
            'zstd',
            '-d',
            '--stdout',
            str(path),
        ),
        stdout=subprocess.PIPE,
    ) as proc:
        line = proc.stdout.readline().decode().strip()
        proc.kill()
    return line


async def load_tables() -> None:
    tables = (User, Changeset, Element, ElementMember)
    index_sqls: dict[str, str] = {}

    async with db_commit() as session:
        # disable triggers
        await session.execute(text('SET session_replication_role TO replica'))

        # copy freeze requires truncate
        print('Truncating tables')
        await session.execute(
            text(f'TRUNCATE {','.join(f'"{t.__tablename__}"' for t in tables)} RESTART IDENTITY CASCADE')
        )

        for table in tables:
            table_name = table.__tablename__

            indexes = (arg for arg in table.__table_args__ if isinstance(arg, Index))
            for index in indexes:
                print(f'Dropping index {index.name!r}')
                sql = await session.scalar(text(f'SELECT pg_get_indexdef({index.name!r}::regclass)'))
                index_sqls[index.name] = sql
                await session.execute(text(f'DROP INDEX {index.name}'))

            path = get_csv_path(table_name)
            header = get_csv_header(path)
            columns = tuple(f'"{c}"' for c in header.split(','))

            print(f'Populating {table_name} table ({len(columns)} columns)...')
            await session.execute(
                text(
                    f'COPY "{table_name}" ({','.join(columns)}) '
                    f"FROM PROGRAM 'zstd -d --stdout \"{path.absolute()}\"' "
                    f'(FORMAT CSV, FREEZE, HEADER TRUE)'
                ),
            )

    async def index_task(sql: str) -> None:
        async with index_semaphore, db() as session:
            await session.connection(execution_options={'isolation_level': 'AUTOCOMMIT'})
            await session.execute(text(sql))

    async with create_task_group() as tg:
        for key, sql in index_sqls.items():
            print(f'Recreating index {key!r}')
            tg.start_soon(index_task, sql)


async def main() -> None:
    async with db_commit() as session:
        if await session.scalar(select(Element).limit(1)):  # noqa: SIM102
            if not input('Database is not empty. Continue? (y/N): ').lower().startswith('y'):
                print('Aborted')
                return

    await load_tables()

    print('Updating statistics')
    await db_update_stats()

    print('Fixing sequence counters consistency')
    await MigrationService.fix_sequence_counters()


if __name__ == '__main__':
    anyio.run(main)
    print('Done! Done! Done!')
