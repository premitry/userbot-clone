"""Outgoing message handler.

Saat user mengetik /command di chat Telegram mana pun, handler ini menjalankan
aksi sesuai konfigurasi Message (edit / delete+send / delete+forward / QRIS /
workflow multi-step). Dynamic QRIS memakai payload per-command (msg.qris_payload)
dan fallback ke Settings global. Forward/Copy mendukung mode latest/specific/random.

Command di-scope PER-AKUN: handler menerima account_id worker sehingga hanya
command milik akun tersebut yang dieksekusi, dan log dicatat atas nama akun itu.

Dynamic Payload Rules (Settings) menentukan perilaku QRIS:
- qris_dynamic_amount: bila "0", QRIS dikirim statis (nominal diabaikan).
- qris_support_short: bila "0", format singkat 5k/25rb/1jt ditolak.
"""

import os
import random
import re

from pyrogram import filters
from pyrogram.handlers import MessageHandler

from database import SessionLocal
from models import AppSetting, ChannelPost, CommandLog, Message, TelegramAccount


def register_handlers(client, account_id=None):
    async def _handler(c, m):
        await _on_outgoing(c, m, account_id=account_id)

    client.add_handler(MessageHandler(_handler, filters.outgoing & filters.text))


def _get_setting(db, key, default=""):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row and row.value is not None else default


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


def _fmt_amount(n):
    return f"{int(n):,}".replace(",", ".")


def _parse_post_url(url):
    if not url:
        return None, None
    m = re.search(r"t\.me/c/(\d+)/(\d+)", url)
    if m:
        return int("-100" + m.group(1)), int(m.group(2))
    m = re.search(r"t\.me/([A-Za-z0-9_]+)/(\d+)", url)
    if m:
        return m.group(1), int(m.group(2))
    return None, None


def _resolve_channel(db, msg):
    """Tentukan (from_chat, message_id) untuk forward/copy sesuai channel_mode."""
    mode = getattr(msg, "channel_mode", "specific") or "specific"
    chat_id = getattr(msg, "channel_chat_id", None)
    if mode in ("latest", "random") and chat_id:
        posts = (
            db.query(ChannelPost)
            .filter(ChannelPost.channel_chat_id == str(chat_id))
            .order_by(ChannelPost.tg_message_id.desc())
            .all()
        )
        if posts:
            p = posts[random.randint(0, len(posts) - 1)] if mode == "random" else posts[0]
            fc, mid = _parse_post_url(p.post_url)
            if fc and mid:
                return fc, mid
            try:
                return int(p.channel_chat_id), p.tg_message_id
            except Exception:
                pass
    return _parse_post_url(msg.channel_post_url)


async def _on_outgoing(client, message, account_id=None):
    text = (message.text or "").strip()
    if not text.startswith("/"):
        return

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    db = SessionLocal()
    try:
        q = db.query(Message).filter(
            Message.command == cmd, Message.is_active == True
        )
        if account_id is not None:
            q = q.filter(Message.account_id == account_id)
        msg = q.first()
        if not msg:
            return

        acc_name = ""
        if account_id is not None:
            acc = db.query(TelegramAccount).filter(
                TelegramAccount.id == account_id
            ).first()
            if acc:
                acc_name = acc.first_name or acc.username or acc.phone or ""

        log = CommandLog(
            command=cmd,
            target_group=str(message.chat.id),
            account_id=account_id,
            account_name=acc_name,
            source="manual",
            message=arg or msg.name,
            status="pending",
        )
        db.add(log)
        db.commit()

        try:
            await _execute(client, message, msg, arg, db)
            log.status = "success"
        except Exception as e:
            low = str(e).lower()
            if "flood" in low:
                log.status = "floodwait"
            elif any(k in low for k in ("permission", "forbidden", "chat_admin", "chat_write", "banned", "restricted")):
                log.status = "no_permission"
            else:
                log.status = "failed"
            log.error = str(e)
        db.commit()
    except Exception as e:
        print(f"\u274c command handler error: {e}")
    finally:
        db.close()


async def _execute(client, message, msg, arg, db):
    chat_id = message.chat.id
    content = (msg.content or "").replace("{arg}", arg)

    # ── Workflow multi-step ──
    if msg.type == "workflow" or (msg.steps and len(msg.steps) > 0):
        from worker.message_sender import run_steps
        try:
            await message.delete()
        except Exception:
            pass
        await run_steps(client, chat_id, msg.steps, db, msg=msg, arg=arg)
        return

    # ── Dynamic QRIS ──
    if msg.type == "dynamic_qris":
        provider = (getattr(msg, "qris_provider", None) or "local").lower()
        if provider == "gatepay":
            await _execute_gatepay_qris(client, message, msg, arg, db)
            return

        from worker.qris_gen import build_dynamic_qris, generate_qris_image, parse_amount
        base = msg.qris_payload if msg.qris_payload else _get_setting(db, "qris_base_payload", "")
        dynamic_on = _get_setting(db, "qris_dynamic_amount", "1") != "0"
        allow_short = _get_setting(db, "qris_support_short", "1") != "0"
        amount = 0
        try:
            if not base:
                raise ValueError("Base QRIS payload belum diatur (set payload di command)")
            if dynamic_on:
                try:
                    amount = parse_amount(arg, allow_short=allow_short)
                except ValueError as ve:
                    raise ValueError(str(ve))
                except Exception:
                    raise ValueError("Format nominal tidak valid. Contoh: /qris 5000 atau /qris 5k")
                payload = build_dynamic_qris(base, amount)
            else:
                payload = base
            img_path = generate_qris_image(
                payload,
                frame=(getattr(msg, "qris_frame", None) or "none"),
                size=(getattr(msg, "qris_size", None) or "small"),
            )
        except ValueError as e:
            try:
                await message.edit_text(f"\u26a0\ufe0f {e}")
            except Exception:
                try:
                    await client.send_message(chat_id, f"\u26a0\ufe0f {e}")
                except Exception:
                    pass
            raise

        pretty = _fmt_amount(amount) if amount else ""
        rp = ("Rp" + pretty) if amount else ""
        caption = None
        if content:
            caption = content.replace("{amount_rp}", rp).replace("{amount}", pretty)
        footer = (msg.qris_footer_text or "").strip()
        if footer:
            footer = footer.replace("{amount_rp}", rp).replace("{amount}", pretty)
            caption = (caption + "\n\n" + footer) if caption else footer
        try:
            await message.delete()
        except Exception:
            pass
        sent = await client.send_photo(chat_id, img_path, caption=caption)
        if img_path and os.path.exists(img_path):
            os.remove(img_path)
        # Auto-delete QRIS setelah N detik (opsional)
        try:
            ttl = int(msg.qris_auto_delete_seconds or 0)
        except Exception:
            ttl = 0
        if ttl > 0 and sent is not None:
            import asyncio as _asyncio
            async def _auto_del(_client, _cid, _mid, _delay):
                try:
                    await _asyncio.sleep(_delay)
                    await _client.delete_messages(_cid, _mid)
                except Exception:
                    pass
            _asyncio.create_task(_auto_del(client, chat_id, sent.id, ttl))
        return

    # ── Forward / Copy channel post ──
    if msg.type in ("forward_channel", "copy_channel"):
        from_chat, mid = _resolve_channel(db, msg)
        if not from_chat or not mid:
            raise ValueError("Channel post tidak ditemukan (cek mode / link / sync)")
        try:
            await message.delete()
        except Exception:
            pass
        if msg.type == "copy_channel":
            await client.copy_message(chat_id, from_chat, mid)
        else:
            await client.forward_messages(chat_id, from_chat, mid)
        return

    # ── Album ──
    if msg.type == "album":
        medias = _media_list(msg.media_url)
        if not medias:
            raise ValueError("Media album kosong")
        from pyrogram.types import InputMediaPhoto
        group = []
        for i, m in enumerate(medias):
            group.append(InputMediaPhoto(m, caption=content if i == 0 else None))
        try:
            await message.delete()
        except Exception:
            pass
        await client.send_media_group(chat_id, group)
        return

    # ── Media (photo/video/document) ──
    if msg.type in ("photo", "video", "document"):
        media = _resolve_media(msg.media_url)
        if not media:
            raise ValueError("Media URL belum diisi")
        try:
            await message.delete()
        except Exception:
            pass
        if msg.type == "photo":
            await client.send_photo(chat_id, media, caption=content or None)
        elif msg.type == "video":
            await client.send_video(chat_id, media, caption=content or None)
        else:
            await client.send_document(chat_id, media, caption=content or None)
        return

    # ── Text (default) ──
    if msg.action == "edit":
        await message.edit_text(content or msg.name)
    else:
        try:
            await message.delete()
        except Exception:
            pass
        await client.send_message(chat_id, content or msg.name)


async def _execute_gatepay_qris(client, message, msg, arg, db):
    """QRIS via GatePay: buat order, kirim QR, simpan PaymentOrder untuk webhook."""
    import asyncio as _asyncio
    from datetime import datetime
    from models import PaymentOrder, TelegramAccount
    from worker.qris_gen import generate_qris_image, parse_amount
    from worker.gatepay_client import GatePayError, create_order

    chat_id = message.chat.id
    content = (msg.content or "").replace("{arg}", arg)

    acc = db.query(TelegramAccount).filter(TelegramAccount.id == msg.account_id).first()
    api_key = (acc.gatepay_api_key or "").strip() if acc else ""
    if not api_key:
        raise ValueError("GatePay API key belum diatur — buka menu Payments → Settings")

    try:
        amount = parse_amount(arg, allow_short=True)
    except Exception:
        raise ValueError("Format nominal tidak valid. Contoh: /qris 5000 atau /qris 5k")

    reference = f"tg_{chat_id}_{message.id}"
    expires_in = int(getattr(acc, "gatepay_expires_in", 0) or 0) or None
    try:
        order = await create_order(api_key, amount, reference=reference, expires_in=expires_in)
    except GatePayError as e:
        try:
            await message.edit_text(f"\u26a0\ufe0f {e}")
        except Exception:
            await client.send_message(chat_id, f"\u26a0\ufe0f {e}")
        raise

    payload = order.get("qris") or ""
    unique_amount = int(order.get("unique_amount") or amount)
    order_id = str(order.get("id") or "")
    checkout_url = order.get("checkout_url") or ""

    img_path = generate_qris_image(
        payload,
        frame=(getattr(msg, "qris_frame", None) or "none"),
        size=(getattr(msg, "qris_size", None) or "small"),
    )

    pretty_base = _fmt_amount(amount)
    pretty_uniq = _fmt_amount(unique_amount)
    replacements = {
        "{amount}": pretty_base,
        "{amount_rp}": "Rp" + pretty_base,
        "{unique}": pretty_uniq,
        "{unique_rp}": "Rp" + pretty_uniq,
        "{checkout_url}": checkout_url,
        "{ref}": reference,
    }
    caption = content or f"💳 Bayar tepat *Rp{pretty_uniq}* (nominal unik).\nHarga: Rp{pretty_base}"
    footer = (msg.qris_footer_text or "").strip()
    if footer:
        caption = caption + "\n\n" + footer
    for k, v in replacements.items():
        caption = caption.replace(k, v)

    try:
        await message.delete()
    except Exception:
        pass

    sent = await client.send_photo(chat_id, img_path, caption=caption)
    if img_path and os.path.exists(img_path):
        os.remove(img_path)

    # Simpan order untuk webhook.
    try:
        po = PaymentOrder(
            account_id=msg.account_id,
            message_id=msg.id,
            provider="gatepay",
            order_id=order_id,
            reference=reference,
            chat_id=str(chat_id),
            chat_title=getattr(message.chat, "title", None) or getattr(message.chat, "first_name", None),
            tg_message_id=sent.id if sent else None,
            base_amount=amount,
            unique_amount=unique_amount,
            status="pending",
            checkout_url=checkout_url,
            qris_payload=payload,
            created_at=datetime.utcnow(),
        )
        db.add(po)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"⚠️ Gagal simpan PaymentOrder: {e}")

    # Auto-delete jika di-set.
    try:
        ttl = int(msg.qris_auto_delete_seconds or 0)
    except Exception:
        ttl = 0
    if ttl > 0 and sent is not None:
        async def _auto_del(_client, _cid, _mid, _delay):
            try:
                await _asyncio.sleep(_delay)
                await _client.delete_messages(_cid, _mid)
            except Exception:
                pass
        _asyncio.create_task(_auto_del(client, chat_id, sent.id, ttl))
