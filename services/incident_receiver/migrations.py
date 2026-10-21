"""Versioned, transactional schema initialization; never silently alters existing tables."""
from sqlalchemy import select, text
from services.incident_receiver.models import Base, SchemaVersion, utcnow

CURRENT_VERSION = 1
LOCK_ID = 864210


def migrate(engine):
    with engine.begin() as connection:
        if engine.dialect.name == 'postgresql':
            connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': LOCK_ID})
        SchemaVersion.__table__.create(connection, checkfirst=True)
        versions = set(connection.execute(select(SchemaVersion.version)).scalars())
        if versions and max(versions) > CURRENT_VERSION:
            raise RuntimeError('Database schema is newer than this application')
        if 1 not in versions:
            # Migration 001: initial normalized incident schema.
            Base.metadata.create_all(connection)
            connection.execute(SchemaVersion.__table__.insert().values(version=1, applied_at=utcnow()))
