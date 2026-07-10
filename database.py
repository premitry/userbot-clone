"""SQLAlchemy database engine and session management."""

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from config import settings

logger = logging.getLogger("database")

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite only
)

# Optimasi SQLite (Mode WAL + Synchronous Normal) — hanya aktif kalau pakai SQLite.
if "sqlite" in settings.DATABASE_URL:
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        except Exception as e:
            logger.warning("Gagal mengaktifkan SQLite WAL/Synchronous: %s", e)
        finally:
            cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency — yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Kolom baru yang mungkin belum ada di DB lama (auto-migrate ringan untuk SQLite).
# Tabel baru dibuat otomatis oleh create_all; ini khusus ADD COLUMN.
_MIGRATIONS = {
    "users": {
        "must_change_password": "BOOLEAN DEFAULT 0",
    },
    "schedules": {
        "message_id": "INTEGER",
        "target_source": "VARCHAR(20) DEFAULT 'manual_targets'",
        "folder_id": "INTEGER",
        "collection_id": "INTEGER",
        "target_group_ids": "TEXT",
        "label_id": "INTEGER",
        "schedule_type": "VARCHAR(20) DEFAULT 'cron'",
        "fixed_times": "TEXT",
        "interval_minutes": "INTEGER",
        "days_active": "VARCHAR(30)",
        "start_time": "VARCHAR(10)",
        "end_time": "VARCHAR(10)",
        "delay_seconds": "INTEGER DEFAULT 0",
        "random_delay_min": "INTEGER DEFAULT 0",
        "random_delay_max": "INTEGER DEFAULT 0",
        "random_order": "BOOLEAN DEFAULT 0",
        "random_message": "BOOLEAN DEFAULT 0",
        "max_per_day": "INTEGER",
        "sent_today": "INTEGER DEFAULT 0",
        "sent_date": "VARCHAR(20)",
        "account_id": "INTEGER",
        "account_mode": "VARCHAR(20) DEFAULT 'fixed'",
        "rr_index": "INTEGER DEFAULT 0",
    },
    "groups": {
        "username": "VARCHAR(100)",
        "type": "VARCHAR(20) DEFAULT 'group'",
        "can_send": "BOOLEAN DEFAULT 1",
        "global_unique_key": "VARCHAR(120)",
        "updated_at": "DATETIME",
    },
    "messages": {
        "qris_min": "INTEGER",
        "qris_max": "INTEGER",
        "qris_payload": "TEXT",
        "qris_auto_delete_seconds": "INTEGER DEFAULT 0",
        "qris_footer_text": "TEXT",
        "qris_frame": "VARCHAR(255) DEFAULT 'none'",
        "qris_size": "VARCHAR(20) DEFAULT 'small'",
        "channel_mode": "VARCHAR(20) DEFAULT 'specific'",
        "channel_chat_id": "VARCHAR(50)",
        "account_id": "INTEGER",
    },
    "command_logs": {
        "source": "VARCHAR(20) DEFAULT 'manual'",
        "account_id": "INTEGER",
    },
}

# Index untuk kolom yang sering difilter (FK & lookup). Dibuat IF NOT EXISTS.
_INDEXES = [
    ("ix_account_targets_account_id", "account_targets", "account_id"),
    ("ix_account_targets_target_id", "account_targets", "target_id"),
    ("ix_target_label_items_label_id", "target_label_items", "label_id"),
    ("ix_target_label_items_group_id", "target_label_items", "group_id"),
    ("ix_tg_folder_members_folder_id", "telegram_folder_members", "folder_id"),
    ("ix_tg_folder_members_target_id", "telegram_folder_members", "target_id"),
    ("ix_mc_members_collection_id", "manual_collection_members", "collection_id"),
    ("ix_mc_members_target_id", "manual_collection_members", "target_id"),
    ("ix_schedules_message_id", "schedules", "message_id"),
    ("ix_schedules_account_id", "schedules", "account_id"),
    ("ix_schedules_folder_id", "schedules", "folder_id"),
    ("ix_schedules_collection_id", "schedules", "collection_id"),
    ("ix_queue_jobs_schedule_id", "queue_jobs", "schedule_id"),
    ("ix_queue_jobs_message_id", "queue_jobs", "message_id"),
    ("ix_workflow_steps_message_id", "workflow_steps", "message_id"),
    ("ix_telegram_folders_account_id", "telegram_folders", "account_id"),
    ("ix_manual_collections_account_id", "manual_collections", "account_id"),
    ("ix_groups_account_id", "groups", "account_id"),
]


def _migrate_message_command_scope(conn, existing_tables):
    """Command jadi unik PER-AKUN (bukan global).

    - Backfill account_id command lama -> akun pertama.
    - Buang unique index global 'ix_messages_command', ganti index biasa.
    - Buat unique index gabungan (account_id, command).
    """
    if "messages" not in existing_tables:
        return
    try:
        first = conn.execute(
            text("SELECT id FROM telegram_accounts ORDER BY id LIMIT 1")
        ).fetchone()
        if first:
            conn.execute(
                text("UPDATE messages SET account_id = :aid WHERE account_id IS NULL"),
                {"aid": first[0]},
            )
        conn.execute(text("DROP INDEX IF EXISTS ix_messages_command"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_messages_command ON messages (command)"
        ))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_account_command "
            "ON messages (account_id, command)"
        ))
    except Exception as e:
        logger.warning("Migrasi command per-akun dilewati: %s", e)


def _encrypt_existing_sessions(conn, existing_tables):
    """Enkripsi session_string plaintext lama -> Fernet (idempotent, sekali jalan)."""
    if "telegram_accounts" not in existing_tables:
        return
    try:
        from crypto import encrypt_session, SESSION_PREFIX
        rows = conn.execute(
            text("SELECT id, session_string FROM telegram_accounts")
        ).fetchall()
        migrated = 0
        for rid, sess in rows:
            if sess and not str(sess).startswith(SESSION_PREFIX):
                conn.execute(
                    text("UPDATE telegram_accounts SET session_string = :s WHERE id = :i"),
                    {"s": encrypt_session(str(sess)), "i": rid},
                )
                migrated += 1
        if migrated:
            logger.info("Enkripsi %d session Telegram lama (plaintext -> Fernet)", migrated)
    except Exception as e:
        logger.warning("Enkripsi session lama dilewati: %s", e)


def _create_indexes(conn, inspector, existing_tables):
    for name, table, column in _INDEXES:
        if table not in existing_tables:
            continue
        try:
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                continue
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({column})"))
        except Exception as e:
            logger.warning("Index %s dilewati: %s", name, e)


def _auto_migrate():
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    with engine.begin() as conn:
        for table, columns in _MIGRATIONS.items():
            if table not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table)}
            for col, ddl in columns.items():
                if col not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
                    logger.info("Migrasi: tambah kolom %s.%s", table, col)

        # Backfill global_unique_key = 'chat:<telegram_id>' bila kosong
        if "groups" in existing_tables:
            try:
                conn.execute(text(
                    "UPDATE groups SET global_unique_key = 'chat:' || telegram_id "
                    "WHERE global_unique_key IS NULL OR global_unique_key = ''"
                ))
            except Exception as e:
                logger.warning("Backfill global_unique_key dilewati: %s", e)

        # Command unik per-akun
        _migrate_message_command_scope(conn, existing_tables)
        # Enkripsi session lama
        _encrypt_existing_sessions(conn, existing_tables)
        # Index performa
        _create_indexes(conn, inspector, existing_tables)


def init_db():
    """Create all tables from models + auto-migrate kolom baru."""
    Base.metadata.create_all(bind=engine)
    try:
        _auto_migrate()
    except Exception as e:
        logger.warning("Auto-migrate dilewati: %s", e)
