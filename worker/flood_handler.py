"""FloodWait-safe send wrappers."""

import asyncio
from pyrogram.errors import FloodWait


async def safe_send(
    client, chat_id: int, text: str, max_retries: int = 3,
) -> bool:
    for attempt in range(max_retries):
        try:
            await client.send_message(chat_id=chat_id, text=text)
            return True
        except FloodWait as e:
            wait = e.value
            print(f"⏳ FloodWait {wait}s (attempt {attempt+1}/{max_retries})")
            await asyncio.sleep(wait + 1)
        except Exception as e:
            print(f"❌ Send error: {e}")
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2)

    raise Exception(f"Gagal kirim pesan ke {chat_id} setelah {max_retries}x")


async def safe_send_photo(
    client, chat_id: int, photo: str, caption: str = "", max_retries: int = 3,
) -> bool:
    for attempt in range(max_retries):
        try:
            await client.send_photo(
                chat_id=chat_id, photo=photo, caption=caption,
            )
            return True
        except FloodWait as e:
            wait = e.value
            print(f"⏳ FloodWait {wait}s (attempt {attempt+1}/{max_retries})")
            await asyncio.sleep(wait + 1)
        except Exception as e:
            print(f"❌ Send photo error: {e}")
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2)

    raise Exception(f"Gagal kirim foto ke {chat_id} setelah {max_retries}x")
