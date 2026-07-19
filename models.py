"""SQLAlchemy ORM models."""

from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, event,
)
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    # Paksa ganti password saat login pertama (mis. akun admin default).
    must_change_password = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class TelegramAccount(Base):
    """Akun Telegram yang terhubung — bisa banyak akun.

    session_string disimpan TERENKRIPSI (Fernet) via event listener di bawah.
    """
    __tablename__ = "telegram_accounts"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), nullable=True)
    username = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    telegram_id = Column(String(50), unique=True, nullable=True)
    session_string = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    is_connected = Column(Boolean, default=False)
    added_at = Column(DateTime, default=datetime.utcnow)
    last_connected = Column(DateTime, nullable=True)
    # GatePay per-akun (boleh sama antar akun, sesuai preferensi user).
    gatepay_api_key = Column(String(255), nullable=True)
    gatepay_callback_secret = Column(String(255), nullable=True)
    gatepay_notify_on_paid = Column(Boolean, default=True)
    gatepay_thanks_text = Column(Text, nullable=True)
    # Berapa lama QRIS aktif sebelum expired (detik). 0/None = pakai default GatePay.
    gatepay_expires_in = Column(Integer, default=900)

    groups = relationship("Group", back_populates="account")
    account_targets = relationship(
        "AccountTarget", back_populates="account", cascade="all, delete-orphan"
    )


class Group(Base):
    """Target chat unik/global (group / channel / private / bot).

    Nama tabel tetap 'groups' untuk kompatibilitas, tapi secara konsep ini
    adalah 'Target' unik. telegram_id menyimpan chat_id Telegram dan menjadi
    dedup key utama. Relasi ke akun (siapa yang join & bisa kirim) disimpan di
    tabel account_targets, sehingga target yang sama TIDAK tampil berulang
    meski banyak akun bergabung.
    """
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String(50), index=True, nullable=False)  # chat_id
    global_unique_key = Column(String(120), unique=True, index=True, nullable=True)
    title = Column(String(255), default="Unknown")
    username = Column(String(100), nullable=True)
    # type: group | channel | private | bot | supergroup
    type = Column(String(20), default="group")
    # can_send/account_id = agregat/last-known untuk kompatibilitas UI lama
    can_send = Column(Boolean, default=True)
    member_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    account_id = Column(Integer, ForeignKey("telegram_accounts.id"), index=True, nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("TelegramAccount", back_populates="groups")
    schedules = relationship("Schedule", back_populates="group")
    label_items = relationship(
        "TargetLabelItem", back_populates="group", cascade="all, delete-orphan"
    )
    account_targets = relationship(
        "AccountTarget", back_populates="target", cascade="all, delete-orphan"
    )


class AccountTarget(Base):
    """Relasi akun Telegram <-> target (groups).

    Satu target unik bisa punya banyak akun. can_send menandai apakah akun ini
    boleh mengirim ke target tersebut.
    """
    __tablename__ = "account_targets"
    __table_args__ = (
        UniqueConstraint("account_id", "target_id", name="uq_account_target"),
    )

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("telegram_accounts.id"), index=True, nullable=False)
    target_id = Column(Integer, ForeignKey("groups.id"), index=True, nullable=False)
    can_send = Column(Boolean, default=True)
    role = Column(String(20), nullable=True)  # creator | admin | member
    is_joined = Column(Boolean, default=True)
    last_synced_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("TelegramAccount", back_populates="account_targets")
    target = relationship("Group", back_populates="account_targets")


class TargetLabel(Base):
    """Label/grup logis untuk mengelompokkan Target."""
    __tablename__ = "target_labels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(255), nullable=True)
    color = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    items = relationship(
        "TargetLabelItem", back_populates="label", cascade="all, delete-orphan"
    )


class TargetLabelItem(Base):
    """Relasi many-to-many antara TargetLabel dan Group (Target)."""
    __tablename__ = "target_label_items"

    id = Column(Integer, primary_key=True, index=True)
    label_id = Column(Integer, ForeignKey("target_labels.id"), index=True, nullable=False)
    group_id = Column(Integer, ForeignKey("groups.id"), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    label = relationship("TargetLabel", back_populates="items")
    group = relationship("Group", back_populates="label_items")


class TelegramFolder(Base):
    """Mirror read-only folder Telegram (dialog filters) via MTProto."""
    __tablename__ = "telegram_folders"
    __table_args__ = (
        UniqueConstraint("account_id", "folder_id", name="uq_account_folder"),
    )

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("telegram_accounts.id"), index=True, nullable=False)
    folder_id = Column(Integer, nullable=False)  # id filter dari Telegram
    name = Column(String(255), default="")
    title = Column(String(255), default="")
    include_peers_json = Column(Text, nullable=True)
    exclude_peers_json = Column(Text, nullable=True)
    raw_json = Column(Text, nullable=True)
    last_synced_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    members = relationship(
        "TelegramFolderMember", back_populates="folder", cascade="all, delete-orphan"
    )


class TelegramFolderMember(Base):
    """Anggota folder Telegram (target di dalam folder)."""
    __tablename__ = "telegram_folder_members"
    __table_args__ = (
        UniqueConstraint("folder_id", "target_id", name="uq_folder_member"),
    )

    id = Column(Integer, primary_key=True, index=True)
    folder_id = Column(Integer, ForeignKey("telegram_folders.id"), index=True, nullable=False)
    target_id = Column(Integer, ForeignKey("groups.id"), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    folder = relationship("TelegramFolder", back_populates="members")


class ManualCollection(Base):
    """Pengelompokan target buatan aplikasi (manual)."""
    __tablename__ = "manual_collections"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("telegram_accounts.id"), index=True, nullable=True)
    name = Column(String(150), nullable=False)
    description = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    members = relationship(
        "ManualCollectionMember", back_populates="collection", cascade="all, delete-orphan"
    )


class ManualCollectionMember(Base):
    """Anggota manual collection."""
    __tablename__ = "manual_collection_members"
    __table_args__ = (
        UniqueConstraint("collection_id", "target_id", name="uq_collection_member"),
    )

    id = Column(Integer, primary_key=True, index=True)
    collection_id = Column(Integer, ForeignKey("manual_collections.id"), index=True, nullable=False)
    target_id = Column(Integer, ForeignKey("groups.id"), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    collection = relationship("ManualCollection", back_populates="members")


class CommandLog(Base):
    __tablename__ = "command_logs"

    id = Column(Integer, primary_key=True, index=True)
    command = Column(String(50), index=True, nullable=False)
    target_group = Column(String(255), default="")
    account_name = Column(String(100), default="")
    account_id = Column(Integer, ForeignKey("telegram_accounts.id"), nullable=True, index=True)
    # source: manual | auto | queue
    source = Column(String(20), default="manual")
    # status: success | failed | floodwait | no_permission | pending
    status = Column(String(20), default="pending")
    message = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    executed_at = Column(DateTime, default=datetime.utcnow)


class Schedule(Base):
    """Auto Share campaign — kirim Message otomatis ke target via jadwal."""
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    message_id = Column(Integer, ForeignKey("messages.id"), index=True, nullable=True)

    # Sumber target: manual_targets | telegram_folder | manual_collection | (legacy: label)
    target_source = Column(String(20), default="manual_targets")
    folder_id = Column(Integer, ForeignKey("telegram_folders.id"), index=True, nullable=True)
    collection_id = Column(Integer, ForeignKey("manual_collections.id"), index=True, nullable=True)

    # Target manual (CSV group DB id) atau via label
    target_group_ids = Column(Text, nullable=True)
    label_id = Column(Integer, ForeignKey("target_labels.id"), index=True, nullable=True)

    # Mode jadwal: cron | fixed_times | interval
    schedule_type = Column(String(20), default="cron")
    cron_expression = Column(String(100), nullable=True)
    fixed_times = Column(Text, nullable=True)          # CSV "08:00,13:00,20:00"
    interval_minutes = Column(Integer, nullable=True)  # mode interval
    days_active = Column(String(30), nullable=True)     # CSV "0,1,2,3,4" (Mon=0)
    start_time = Column(String(10), nullable=True)      # "08:00"
    end_time = Column(String(10), nullable=True)        # "22:00"

    # Kontrol pengiriman
    delay_seconds = Column(Integer, default=0)
    random_delay_min = Column(Integer, default=0)
    random_delay_max = Column(Integer, default=0)
    random_order = Column(Boolean, default=False)
    random_message = Column(Boolean, default=False)     # acak Message tiap kirim
    max_per_day = Column(Integer, nullable=True)
    sent_today = Column(Integer, default=0)
    sent_date = Column(String(20), nullable=True)       # "2026-07-03"

    # Pemilihan akun pengirim: fixed | random | round_robin | least_used
    account_id = Column(Integer, ForeignKey("telegram_accounts.id"), index=True, nullable=True)
    account_mode = Column(String(20), default="fixed")
    rr_index = Column(Integer, default=0)              # state round-robin

    is_active = Column(Boolean, default=True)
    last_run = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Legacy (kompatibilitas campaign lama)
    command = Column(String(50), nullable=True)
    message_text = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)
    group_id = Column(Integer, ForeignKey("groups.id"), index=True, nullable=True)

    group = relationship("Group", back_populates="schedules")


class QueueJob(Base):
    """Antrian eksekusi Auto Share (progress realtime)."""
    __tablename__ = "queue_jobs"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), default="")
    schedule_id = Column(Integer, ForeignKey("schedules.id"), index=True, nullable=True)
    message_id = Column(Integer, ForeignKey("messages.id"), index=True, nullable=True)
    # status: waiting | running | paused | done | error | canceled
    status = Column(String(20), default="waiting")
    current_target = Column(String(255), nullable=True)
    completed = Column(Integer, default=0)
    total = Column(Integer, default=0)
    success_count = Column(Integer, default=0)
    failed_count = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)


class Message(Base):
    """Custom command yang dipakai langsung di chat Telegram (mis. /pay, /qris).

    Command unik PER-AKUN: kombinasi (account_id, command) yang harus unik,
    sehingga /pay bisa ada di akun A dan akun B dengan konfigurasi berbeda.
    """
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("account_id", "command", name="uq_messages_account_command"),
    )

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("telegram_accounts.id"), nullable=True, index=True)
    command = Column(String(50), index=True, nullable=False)
    name = Column(String(100), nullable=False)
    # type: text | photo | video | document | album | forward_channel | copy_channel | dynamic_qris | workflow
    type = Column(String(20), default="text")
    # action: edit | delete_send | delete_forward
    action = Column(String(30), default="edit")
    content = Column(Text, nullable=True)
    media_url = Column(String(1000), nullable=True)
    channel_post_url = Column(String(500), nullable=True)
    # Forward/Copy channel mode: latest | specific | random
    channel_mode = Column(String(20), default="specific")
    channel_chat_id = Column(String(50), nullable=True)
    # Dynamic QRIS: payload base (hasil decode gambar / paste manual) + batas nominal
    qris_payload = Column(Text, nullable=True)
    qris_min = Column(Integer, nullable=True)
    qris_max = Column(Integer, nullable=True)
    # Auto-hapus pesan QRIS setelah N detik (0/NULL = tidak dihapus)
    qris_auto_delete_seconds = Column(Integer, nullable=True, default=0)
    # Teks tambahan yang ditempel di bawah caption QRIS (biar tidak polos)
    qris_footer_text = Column(Text, nullable=True)
    # Frame QRIS: 'none' | 'classic' | 'modern' | 'minimal' | URL gambar custom (/static/... atau http)
    qris_frame = Column(String(255), nullable=True, default="none")
    # Ukuran QR: 'small' (default) | 'medium' | 'large'
    qris_size = Column(String(20), nullable=True, default="small")
    # Provider QRIS: 'local' (default, offline generate) | 'gatepay' (auto-confirm)
    qris_provider = Column(String(20), nullable=True, default="local")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    steps = relationship(
        "WorkflowStep",
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="WorkflowStep.position",
    )


class WorkflowStep(Base):
    """Step dalam sebuah Message (workflow multi-langkah)."""
    __tablename__ = "workflow_steps"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), index=True, nullable=False)
    position = Column(Integer, default=0)
    # step_type: edit_text | send_media | forward_channel | dynamic_qris | delay
    step_type = Column(String(30), default="edit_text")
    content = Column(Text, nullable=True)
    media_url = Column(String(1000), nullable=True)
    channel_post_url = Column(String(500), nullable=True)
    delay_seconds = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    message = relationship("Message", back_populates="steps")


class MediaLibrary(Base):
    """Media yang diupload sekali, bisa dipakai ulang di banyak Message."""
    __tablename__ = "media_library"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), default="")
    url = Column(String(1000), nullable=False)
    # kind: photo | video | document
    kind = Column(String(20), default="photo")
    mime_type = Column(String(100), nullable=True)
    size = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChannelPost(Base):
    """Cache postingan channel hasil sync (untuk forward/copy)."""
    __tablename__ = "channel_posts"

    id = Column(Integer, primary_key=True, index=True)
    channel_chat_id = Column(String(50), index=True, nullable=False)
    channel_title = Column(String(255), default="")
    channel_username = Column(String(100), nullable=True)
    tg_message_id = Column(Integer, nullable=False)
    preview = Column(Text, nullable=True)
    has_media = Column(Boolean, default=False)
    post_url = Column(String(500), nullable=True)
    posted_at = Column(DateTime, nullable=True)
    synced_at = Column(DateTime, default=datetime.utcnow)


class AppSetting(Base):
    """Key-value settings (mis. qris_base_payload)."""
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class BotStatus(Base):
    __tablename__ = "bot_status"

    id = Column(Integer, primary_key=True, index=True)
    is_running = Column(Boolean, default=False)
    active_accounts = Column(Integer, default=0)
    uptime_start = Column(DateTime, nullable=True)
    total_commands = Column(Integer, default=0)
    total_errors = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow)


class PaymentOrder(Base):
    """Order pembayaran GatePay — 1 baris per /qris (mode gatepay).

    Dipakai untuk: (a) mapping webhook order.paid -> chat asal, (b) rekap
    pemasukan di menu Payments, (c) auto-reply "lunas" ke customer.
    """
    __tablename__ = "payment_orders"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("telegram_accounts.id"), index=True, nullable=True)
    message_id = Column(Integer, ForeignKey("messages.id"), index=True, nullable=True)
    provider = Column(String(20), default="gatepay")
    # ID order dari provider (mis. ord_xxx). Unik agar webhook idempotent.
    order_id = Column(String(120), unique=True, index=True, nullable=False)
    reference = Column(String(120), index=True, nullable=True)
    chat_id = Column(String(50), index=True, nullable=True)
    chat_title = Column(String(255), nullable=True)
    tg_message_id = Column(Integer, nullable=True)  # id pesan QR di Telegram (untuk hapus/reply)
    base_amount = Column(Integer, default=0)
    unique_amount = Column(Integer, default=0)
    # status: pending | paid | expired | cancelled | failed
    status = Column(String(20), default="pending", index=True)
    checkout_url = Column(String(500), nullable=True)
    qris_payload = Column(Text, nullable=True)
    raw_response = Column(Text, nullable=True)
    paid_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Enkripsi session string otomatis (Fernet) ──────────────────────────
# Nilai session_string SELALU disimpan terenkripsi ke DB. Idempotent, jadi
# update biasa (mis. update username/is_connected) tidak merusak nilai.
@event.listens_for(TelegramAccount, "before_insert")
@event.listens_for(TelegramAccount, "before_update")
def _encrypt_account_session(mapper, connection, target):  # noqa: ANN001
    if getattr(target, "session_string", None):
        from crypto import encrypt_session
        target.session_string = encrypt_session(target.session_string)
