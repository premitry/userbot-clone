"""Command: /share — share pesan ke grup."""

from worker.flood_handler import safe_send


async def execute_share(client, target_group_id: str, message: str = None):
    text = message or "📤 Pesan di-share dari dashboard."
    await safe_send(client=client, chat_id=int(target_group_id), text=text)