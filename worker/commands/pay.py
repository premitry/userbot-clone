"""Command: /pay — kirim pesan pembayaran."""

from worker.flood_handler import safe_send


async def execute_pay(client, target_group_id: str, message: str = None):
    text = message or "💳 *Pembayaran berhasil diproses.*\nTerima kasih!"
    await safe_send(client=client, chat_id=int(target_group_id), text=text)