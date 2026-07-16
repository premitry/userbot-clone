"""Kirim Message (custom command) ke sebuah chat — dipakai Auto Share / Queue.

Mengirim (bukan meng-edit) konten Message sesuai tipe, termasuk workflow
multi-step, Forward/Copy channel (mode latest/specific/random), dan Dynamic
QRIS dengan payload per-command + variabel caption.

Auto Share memilih Message berdasarkan message_id lalu menjalankan sesuai type
(tidak mengetik trigger). Untuk dynamic_qris di Auto Share, nominal diambil dari
amount default (qris_min dipakai sebagai Nominal Default); jika kosong, message
di-skip dengan error jelas.
"""

import asyncio
import os

from worker.flood_handler import safe_send, safe_send_photo, safe_forward


def _resolve_media(m):
    if m and m.startswith("/static/"):
        return m.lstrip("/")
    return m


def _media_list(raw):
    if not raw:
        return []
    out = []
    for chunk in raw.replace(",", "\n").split("\n"):
        chunk = chunk.strip()
        if chunk:
            out.append(_resolve_media(chunk))
    return out


def _fmt_amount(n: int) -> str:
    return f"{int(n):,}".replace(",", ".")


def _qris_caption(template: str, amount: int) -> str:
    pretty = _fmt_amount(amount)
    rp = "Rp" + pretty
    text = template or ""
    text = text.replace("{amount_rp}", rp).replace("{amount}", pretty)
    return text


def _default_amount(msg):
    """Nominal default untuk Auto Share (disimpan di kolom qris_min)."""
    if msg is None:
        return None
    return getattr(msg, "qris_min", None)


async def _send_qris(client, chat_id, db, amount_text, caption_template, msg):
    from worker.command_handler import _get_setting
    from worker.qris_gen import build_dynamic_qris, generate_qris_image, parse_amount

    base = (msg.qris_payload if (msg and msg.qris_payload) else _get_setting(db, "qris_base_payload", ""))
    if not base:
        raise ValueError("Base QRIS payload belum diatur (upload gambar QRIS / paste payload di command)")
    try:
        amount = parse_amount(amount_text)
    except Exception:
        raise ValueError("Format nominal tidak valid. Contoh: /qris 5000 atau /qris 5k")
    payload = build_dynamic_qris(base, amount)
    img = generate_qris_image(
        payload,
        frame=(getattr(msg, "qris_frame", None) or "none"),
        size=(getattr(msg, "qris_size", None) or "small"),
    )
    cap = _qris_caption(caption_template, amount)
    try:
        await safe_send_photo(client, chat_id, img, cap)
    finally:
        if img and os.path.exists(img):
            os.remove(img)


async def run_steps(client, chat_id, steps, db, msg=None, arg=""):
    """Jalankan workflow multi-step dalam mode kirim."""
    from worker.command_handler import _parse_post_url

    for st in steps:
        t = st.step_type
        if t == "delay":
            await asyncio.sleep(st.delay_seconds or 0)
        elif t == "edit_text":
            await safe_send(client, chat_id, st.content or "")
        elif t == "send_media":
            media = _resolve_media(st.media_url)
            if media:
                await safe_send_photo(client, chat_id, media, st.content or "")
        elif t == "forward_channel":
            fc, mid = _parse_post_url(st.channel_post_url)
            if fc and mid:
                await safe_forward(client, chat_id, fc, mid)
        elif t == "dynamic_qris":
            default_amt = _default_amount(msg)
            amount_text = st.content or (str(default_amt) if default_amt else arg)
            await _send_qris(client, chat_id, db, amount_text, "", msg)


async def send_message_to_chat(client, chat_id, msg, db, arg=""):
    """Eksekusi 1 Message ke chat sesuai type. Dipakai Auto Share / Queue.

    - text            : kirim content
    - photo/video/doc : kirim media + caption
    - album           : kirim media group
    - forward_channel : forward dari channel (mode latest/specific/random)
    - copy_channel    : copy dari channel
    - dynamic_qris    : hanya untuk Auto Share bila amount default terisi;
                        kalau kosong -> error (skip)
    - workflow        : jalankan langkah-langkah
    """
    content = (msg.content or "").replace("{arg}", arg)
    t = msg.type

    if t == "workflow" or (msg.steps and len(msg.steps) > 0):
        await run_steps(client, chat_id, msg.steps, db, msg=msg, arg=arg)
        return

    if t == "dynamic_qris":
        # Auto Share tidak mengetik command -> tak ada nominal manual.
        # Pakai amount default (qris_min). Jika kosong, jangan dipakai.
        default_amt = _default_amount(msg)
        amount_text = arg or (str(default_amt) if default_amt else "")
        if not amount_text:
            raise ValueError(
                "Dynamic QRIS butuh amount default untuk Auto Share "
                "(isi Nominal Default pada command)"
            )
        await _send_qris(client, chat_id, db, amount_text, content, msg)
        return

    if t in ("forward_channel", "copy_channel"):
        from worker.command_handler import _resolve_channel
        from_chat, mid = _resolve_channel(db, msg)
        if not from_chat or not mid:
            raise ValueError("Channel post tidak ditemukan (cek mode / link / sync)")
        await safe_forward(client, chat_id, from_chat, mid, copy=(t == "copy_channel"))
        return

    if t == "album":
        medias = _media_list(msg.media_url)
        if not medias:
            raise ValueError("Media album kosong")
        from pyrogram.types import InputMediaPhoto
        group = []
        for i, m in enumerate(medias):
            group.append(InputMediaPhoto(m, caption=content if i == 0 else None))
        await client.send_media_group(chat_id, group)
        return

    if t in ("photo", "video", "document"):
        media = _resolve_media(msg.media_url)
        if not media:
            raise ValueError("Media URL belum diisi")
        if t == "photo":
            await safe_send_photo(client, chat_id, media, content or "")
        elif t == "video":
            await client.send_video(chat_id, media, caption=content or None)
        else:
            await client.send_document(chat_id, media, caption=content or None)
        return

    await safe_send(client, chat_id, content or msg.name)
