"""Pydantic request/response schemas."""

from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# ── Auth ──
class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ── Telegram Account ──
class AccountAddPhone(BaseModel):
    phone: str


class AccountVerifyOTP(BaseModel):
    phone: str
    code: str
    phone_code_hash: str


class AccountVerify2FA(BaseModel):
    password: str


class AccountAddSession(BaseModel):
    session_string: str


class AccountResponse(BaseModel):
    id: int
    phone: Optional[str] = None
    username: Optional[str] = None
    first_name: Optional[str] = None
    telegram_id: Optional[str] = None
    is_active: bool
    is_connected: bool
    added_at: datetime

    class Config:
        from_attributes = True


class ActiveAccountSet(BaseModel):
    account_id: int


# ── Command (legacy manual execute) ──
class CommandExecute(BaseModel):
    command: str
    target_group_id: str
    account_id: Optional[int] = None
    message: Optional[str] = None
    image_url: Optional[str] = None


class CommandLogResponse(BaseModel):
    id: int
    command: str
    target_group: str
    account_name: str = ""
    account_id: Optional[int] = None
    source: str = "manual"
    status: str
    message: Optional[str] = None
    error: Optional[str] = None
    executed_at: datetime

    class Config:
        from_attributes = True


# ── Target (dulu Group) ──
class AccountTargetInfo(BaseModel):
    account_id: int
    account_name: str = ""
    can_send: bool = True
    role: Optional[str] = None
    is_joined: bool = True


class TargetResponse(BaseModel):
    id: int
    telegram_id: str
    title: str
    username: Optional[str] = None
    type: str = "group"
    can_send: bool = True
    member_count: int = 0
    is_active: bool = True
    account_count: int = 0
    sendable_count: int = 0
    accounts: list[AccountTargetInfo] = []
    joined_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# alias lama tetap didukung
GroupResponse = TargetResponse


# ── Target Labels ──
class TargetLabelCreate(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = None


class TargetLabelUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None


class TargetLabelResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    group_ids: list[int] = []
    count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class TargetLabelAssign(BaseModel):
    group_ids: list[int]


# ── Telegram Folders (mirror read-only) ──
class TelegramFolderResponse(BaseModel):
    id: int
    account_id: int
    folder_id: int
    name: str = ""
    title: str = ""
    count: int = 0
    last_synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Manual Collections ──
class ManualCollectionCreate(BaseModel):
    name: str
    description: Optional[str] = None
    account_id: Optional[int] = None


class ManualCollectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ManualCollectionResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool = True
    count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class CollectionMemberAction(BaseModel):
    target_ids: list[int] = []


# ── Schedule / Auto Share campaign ──
class ScheduleCreate(BaseModel):
    name: str
    message_id: Optional[int] = None
    # Sumber target: manual_targets | telegram_folder | manual_collection
    target_source: Optional[str] = "manual_targets"
    folder_id: Optional[int] = None
    collection_id: Optional[int] = None
    target_group_ids: Optional[list[int]] = None
    label_id: Optional[int] = None

    schedule_type: str = "cron"  # cron | fixed_times | interval
    cron_expression: Optional[str] = None
    fixed_times: Optional[list[str]] = None       # ["08:00","13:00"]
    interval_minutes: Optional[int] = None
    days_active: Optional[list[int]] = None        # [0,1,2,3,4]
    start_time: Optional[str] = None
    end_time: Optional[str] = None

    delay_seconds: Optional[int] = 0
    random_delay_min: Optional[int] = 0
    random_delay_max: Optional[int] = 0
    random_order: Optional[bool] = False
    random_message: Optional[bool] = False
    max_per_day: Optional[int] = None

    account_id: Optional[int] = None
    account_mode: Optional[str] = "fixed"  # fixed | random | round_robin | least_used

    # legacy
    command: Optional[str] = None
    message_text: Optional[str] = None
    image_url: Optional[str] = None
    group_id: Optional[int] = None


class ScheduleResponse(BaseModel):
    id: int
    name: str
    message_id: Optional[int] = None
    target_source: Optional[str] = "manual_targets"
    folder_id: Optional[int] = None
    collection_id: Optional[int] = None
    target_group_ids: Optional[str] = None
    label_id: Optional[int] = None
    schedule_type: Optional[str] = "cron"
    cron_expression: Optional[str] = None
    fixed_times: Optional[str] = None
    interval_minutes: Optional[int] = None
    days_active: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    delay_seconds: Optional[int] = 0
    random_delay_min: Optional[int] = 0
    random_delay_max: Optional[int] = 0
    random_order: Optional[bool] = False
    random_message: Optional[bool] = False
    max_per_day: Optional[int] = None
    sent_today: Optional[int] = 0
    account_id: Optional[int] = None
    account_mode: Optional[str] = "fixed"
    is_active: bool
    last_run: Optional[datetime] = None
    created_at: datetime
    command: Optional[str] = None
    message_text: Optional[str] = None
    image_url: Optional[str] = None
    group_id: Optional[int] = None

    class Config:
        from_attributes = True


class ScheduleToggle(BaseModel):
    is_active: bool


# ── Queue ──
class QueueJobResponse(BaseModel):
    id: int
    name: str = ""
    schedule_id: Optional[int] = None
    message_id: Optional[int] = None
    status: str
    current_target: Optional[str] = None
    completed: int = 0
    total: int = 0
    success_count: int = 0
    failed_count: int = 0
    error: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class QueueAction(BaseModel):
    action: str  # pause | resume | cancel


# ── Workflow steps ──
class WorkflowStepIn(BaseModel):
    step_type: str = "edit_text"  # edit_text | send_media | forward_channel | dynamic_qris | delay
    content: Optional[str] = None
    media_url: Optional[str] = None
    channel_post_url: Optional[str] = None
    delay_seconds: Optional[int] = 0


class WorkflowStepResponse(BaseModel):
    id: int
    position: int
    step_type: str
    content: Optional[str] = None
    media_url: Optional[str] = None
    channel_post_url: Optional[str] = None
    delay_seconds: Optional[int] = 0

    class Config:
        from_attributes = True


# ── Message (custom command) ──
class MessageCreate(BaseModel):
    command: str
    name: str
    type: str = "text"
    action: str = "edit"
    content: Optional[str] = None
    media_url: Optional[str] = None
    channel_post_url: Optional[str] = None
    channel_mode: Optional[str] = "specific"  # latest | specific | random
    channel_chat_id: Optional[str] = None
    qris_payload: Optional[str] = None
    qris_min: Optional[int] = None
    qris_max: Optional[int] = None
    qris_auto_delete_seconds: Optional[int] = 0
    qris_footer_text: Optional[str] = None
    qris_frame: Optional[str] = "none"
    qris_size: Optional[str] = "small"
    is_active: Optional[bool] = True
    steps: Optional[list[WorkflowStepIn]] = None


class MessageUpdate(BaseModel):
    command: Optional[str] = None
    name: Optional[str] = None
    type: Optional[str] = None
    action: Optional[str] = None
    content: Optional[str] = None
    media_url: Optional[str] = None
    channel_post_url: Optional[str] = None
    channel_mode: Optional[str] = None
    channel_chat_id: Optional[str] = None
    qris_payload: Optional[str] = None
    qris_min: Optional[int] = None
    qris_max: Optional[int] = None
    qris_auto_delete_seconds: Optional[int] = None
    qris_footer_text: Optional[str] = None
    qris_frame: Optional[str] = None
    qris_size: Optional[str] = None
    is_active: Optional[bool] = None
    steps: Optional[list[WorkflowStepIn]] = None


class MessageResponse(BaseModel):
    id: int
    account_id: Optional[int] = None
    command: str
    name: str
    type: str
    action: str
    content: Optional[str] = None
    media_url: Optional[str] = None
    channel_post_url: Optional[str] = None
    channel_mode: Optional[str] = "specific"
    channel_chat_id: Optional[str] = None
    qris_payload: Optional[str] = None
    qris_min: Optional[int] = None
    qris_max: Optional[int] = None
    qris_auto_delete_seconds: Optional[int] = 0
    qris_footer_text: Optional[str] = None
    qris_frame: Optional[str] = "none"
    qris_size: Optional[str] = "small"
    is_active: bool
    created_at: datetime
    steps: list[WorkflowStepResponse] = []

    class Config:
        from_attributes = True


# ── Media Library ──
class MediaLibraryResponse(BaseModel):
    id: int
    name: str = ""
    url: str
    kind: str = "photo"
    mime_type: Optional[str] = None
    size: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


# ── Channel Library ──
class ChannelSyncRequest(BaseModel):
    channel: str          # username / link / chat_id
    limit: Optional[int] = 30
    account_id: Optional[int] = None


class ChannelPostResponse(BaseModel):
    id: int
    channel_chat_id: str
    channel_title: str = ""
    channel_username: Optional[str] = None
    tg_message_id: int
    preview: Optional[str] = None
    has_media: bool = False
    post_url: Optional[str] = None
    posted_at: Optional[datetime] = None
    synced_at: datetime

    class Config:
        from_attributes = True


# ── Settings ──
class SettingsUpdate(BaseModel):
    qris_base_payload: Optional[str] = None
    app_name: Optional[str] = None
    accent_color: Optional[str] = None
    default_language: Optional[str] = None
    qris_dynamic_amount: Optional[bool] = None
    qris_support_short: Optional[bool] = None


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


class ChangeUsername(BaseModel):
    current_password: str
    new_username: str


# ── Dashboard ──
class DashboardStats(BaseModel):
    bot_running: bool
    active_accounts: int
    uptime: Optional[str] = None
    total_groups: int
    total_commands: int
    total_errors: int
    recent_logs: list[CommandLogResponse]
