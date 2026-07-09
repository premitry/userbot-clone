"""Command: /qris — kirim gambar QRIS ke grup."""

import os
import httpx
from worker.flood_handler import safe_send, safe_send_photo


async def execute_qris(
    client,
    target_group_id: str,
    message: str = None,
    image_url: str = None,
):
    caption = message or "📱 Scan QRIS di atas untuk melakukan pembayaran."
    chat_id = int(target_group_id)

    if image_url:
        tmp_path = "/tmp/qris_temp.jpg"
        try:
            async with httpx.AsyncClient() as http:
                resp = await http.get(image_url)
                if resp.status_code == 200:
                    with open(tmp_path, "wb") as f:
                        f.write(resp.content)
                    await safe_send_photo(
                        client=client,
                        chat_id=chat_id,
                        photo=tmp_path,
                        caption=caption,
                    )
                    return
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        # fallback jika download gagal
        await safe_send(
            client=client,
            chat_id=chat_id,
            text=f"{caption}\n\n🔗 {image_url}",
        )
    else:
        await safe_send(client=client, chat_id=chat_id, text=caption)