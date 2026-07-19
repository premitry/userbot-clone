"""Entry point — Telegram Userbot Dashboard."""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import settings
from database import SessionLocal, init_db
from auth import create_default_user

from routers.auth_router import router as auth_router
from routers.commands import router as commands_router
from routers.messages import router as messages_router
from routers.settings import router as settings_router
from routers.schedules import router as schedules_router
from routers.groups import router as groups_router
from routers.labels import router as labels_router
from routers.folders import router as folders_router
from routers.collections import router as collections_router
from routers.media import router as media_router
from routers.channels import router as channels_router
from routers.queue import router as queue_router
from routers.targets import router as targets_router
from routers.dashboard import router as dashboard_router
from routers.accounts import router as accounts_router
from routers.gatepay import router as gatepay_router
from routers.webhooks import router as webhooks_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Starting Telegram Userbot Dashboard...")

    init_db()
    print("✅ Database initialized")

    db = SessionLocal()
    try:
        create_default_user(db)
    finally:
        db.close()

    from worker.client import init_all_workers
    await init_all_workers()

    from worker.scheduler import init_scheduler
    init_scheduler()

    print("✅ All systems ready!")
    print(f"🌐 http://localhost:{settings.APP_PORT}")

    yield

    print("🛑 Shutting down...")
    from worker.client import shutdown_all_workers
    await shutdown_all_workers()

    from worker.scheduler import scheduler
    if scheduler.running:
        scheduler.shutdown()


app = FastAPI(
    title="Telegram Userbot Dashboard",
    version="3.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(auth_router)
app.include_router(accounts_router)
app.include_router(commands_router)
app.include_router(messages_router)
app.include_router(settings_router)
app.include_router(schedules_router)
app.include_router(groups_router)
app.include_router(labels_router)
app.include_router(folders_router)
app.include_router(collections_router)
app.include_router(media_router)
app.include_router(channels_router)
app.include_router(queue_router)
app.include_router(targets_router)
app.include_router(dashboard_router)
app.include_router(gatepay_router)
app.include_router(webhooks_router)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG,
    )
