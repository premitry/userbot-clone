"""Dynamic QRIS payload generator + decoder (EMVCo standard).

- decode_qris_from_image: baca payload EMVCo dari gambar QRIS statis (pyzbar).
- build_dynamic_qris: ubah QRIS statis -> dinamis dgn nominal (recompute CRC).

UPDATE 2026-07-07: Dynamic QRIS sekarang STRICT hanya terima angka penuh murni.
Short format (5k, 5K, 10rb, 25.000, Rp10000) DITOLAK total.

UI toggle 'Support Short Amount' sudah tidak berpengaruh lagi karena enforcement dilakukan di backend.
"""

_INVISIBLE_CHARS = ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060")


def _crc16(payload: str) -> str:
    crc = 0xFFFF
    for ch in payload.encode("ascii"):
        crc ^= ch << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return format(crc, "04X")


def parse_amount(text: str, allow_short: bool = False) -> int:
    """STRICT: hanya menerima string digit murni (angka penuh).

    Diterima: '10000', '25000', '50000', 10000 (int)
    Ditolak: '5k', '5K', '10rb', '25.000', '25,000', 'Rp10000', 'abc'

    allow_short param diabaikan (untuk kompatibilitas backward call site).
    """
    t = "" if text is None else str(text)
    t = t.strip()
    # buang karakter invisible yang kadang ikut ter-kirim dari keyboard HP (BOM, zero-width, dll)
    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060"):
        t = t.replace(ch, "")
    t = t.strip()
    if not t.isdigit():
        raise ValueError("Format nominal tidak valid. Gunakan angka penuh, contoh: /qris 10000")
    amount_int = int(t)
    if amount_int <= 0:
        raise ValueError("Nominal harus lebih dari 0")
    return amount_int


def _parse_tlv(s: str):
    """Parse rantai TLV EMVCo, dengan validasi agar payload rusak tidak crash dengan trace Python.

    Returns list of (tag, value). Kalau struktur tidak valid (tag/length bukan digit,
    value terpotong), raise ValueError dengan pesan ramah.
    """
    out = []
    i = 0
    n = len(s)
    while i + 4 <= n:
        tag = s[i:i + 2]
        lraw = s[i + 2:i + 4]
        if not tag.isdigit() or not lraw.isdigit():
            raise ValueError(
                f"Base QRIS payload rusak (field tidak valid di posisi {i}). "
                "Klik Decode dari gambar QRIS lagi di halaman Command lalu simpan ulang."
            )
        length = int(lraw)
        if i + 4 + length > n:
            raise ValueError(
                "Base QRIS payload rusak (ujung payload terpotong). "
                "Silakan upload ulang gambar QRIS statis."
            )
        val = s[i + 4:i + 4 + length]
        out.append((tag, val))
        i += 4 + length
    if i != n:
        raise ValueError(
            f"Base QRIS payload rusak (sisa data tidak valid di posisi {i}). "
            "Klik Decode dari gambar QRIS lagi di halaman Command lalu simpan ulang."
        )
    return out


def normalize_qris_payload(payload: str) -> str:
    """Bersihkan payload tanpa merusak spasi di dalam value TLV.

    Spasi biasa adalah karakter valid di payload QRIS (contoh nama merchant
    "Ahmad Yahya"). Sebelumnya semua spasi dihapus, sehingga length TLV tidak
    cocok dan payload valid dari hasil upload bisa rusak di posisi berikutnya.
    """
    base = "" if payload is None else str(payload)
    for ch in ("\r", "\n", "\t", *_INVISIBLE_CHARS):
        base = base.replace(ch, "")
    return base.strip()


def validate_qris_payload(payload: str) -> str:
    base = normalize_qris_payload(payload)
    if not base:
        raise ValueError("Base QRIS payload belum diatur")
    if not base.isascii():
        raise ValueError(
            "Base QRIS payload mengandung karakter non-ASCII. "
            "Decode ulang dari gambar QRIS statis lewat halaman Command."
        )
    fields = _parse_tlv(base)
    if not fields or fields[0] != ("00", "01"):
        raise ValueError("Payload yang terbaca bukan payload QRIS/EMVCo yang valid")
    return base


def decode_qris_from_image(path: str) -> str:
    """Decode payload EMVCo dari gambar QR. Butuh pyzbar + lib sistem zbar."""
    try:
        from pyzbar.pyzbar import decode as _decode
        from PIL import Image
    except Exception as e:
        raise ValueError(
            "Library decode QR belum terpasang (pyzbar/zbar). "
            "Install: pip install pyzbar && (Debian/Ubuntu) apt install libzbar0 / "
            "(RHEL/Fedora) dnf install zbar. Detail: " + str(e)
        )

    img = Image.open(path)
    results = _decode(img)
    if not results:
        # coba grayscale untuk QR yang kontrasnya rendah
        results = _decode(img.convert("L"))
    if not results:
        raise ValueError("QR tidak terbaca dari gambar")

    for r in results:
        try:
            data = r.data.decode("utf-8", "ignore").strip()
        except Exception:
            continue
        if data.startswith("00"):  # EMVCo payload diawali tag 00 (000201...)
            return validate_qris_payload(data)
    # fallback: validasi hasil pertama supaya payload rusak tidak tersimpan
    return validate_qris_payload(results[0].data.decode("utf-8", "ignore"))


def build_dynamic_qris(base_payload: str, amount) -> str:
    """Bangun payload QRIS dinamis dari payload statis + nominal.

    amount boleh int/float/string.
    SEMUA path WAJIB lewat parse_amount() untuk validasi digit murni.
    TIDAK PERNAH int(amount) sebelum validasi isdigit.
    Short format otomatis ditolak oleh parse_amount.
    """
    base = validate_qris_payload(base_payload)

    # ── Normalisasi amount (strict via parse_amount, no direct int before check) ──
    if isinstance(amount, bool):
        raise ValueError("Format nominal tidak valid. Gunakan angka penuh, contoh: /qris 10000")
    try:
        amount_int = parse_amount(amount)  # str/int both handled inside, validation first
    except ValueError as ve:
        # propagate clean message
        raise ve
    except Exception:
        raise ValueError("Format nominal tidak valid. Gunakan angka penuh, contoh: /qris 10000")

    if amount_int <= 0:
        raise ValueError("Nominal harus lebih dari 0")

    data = {}
    try:
        for tag, val in _parse_tlv(base):
            data[tag] = val
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(
            "Base QRIS payload tidak valid / rusak. "
            f"Silakan upload ulang gambar QRIS statis. Detail: {e}"
        )

    data["01"] = "12"            # dynamic
    data.pop("63", None)          # drop old CRC
    data["54"] = str(amount_int)  # transaction amount

    body = ""
    for tag in sorted(data.keys(), key=lambda x: int(x)):
        val = data[tag]
        body += tag + str(len(val)).zfill(2) + val
    body += "6304"
    return body + _crc16(body)


_SIZE_PRESET = {
    "small": {"box": 6, "border": 2, "final": 520},
    "medium": {"box": 8, "border": 3, "final": 680},
    "large": {"box": 10, "border": 4, "final": 860},
}

_FRAME_PRESETS = ("none", "classic", "modern", "minimal")


def _render_qr(payload: str, size: str = "small"):
    """Render QR code sebagai PIL.Image RGB dengan ukuran yg lebih kecil dari default."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    cfg = _SIZE_PRESET.get(size or "small", _SIZE_PRESET["small"])
    qr = qrcode.QRCode(
        error_correction=ERROR_CORRECT_M,
        box_size=cfg["box"],
        border=cfg["border"],
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img, cfg


def _draw_preset_frame(qr_img, preset: str, cfg: dict):
    """Bungkus QR dengan frame preset sederhana (classic/modern/minimal)."""
    from PIL import Image, ImageDraw, ImageFont

    pad = 40
    header_h = 70 if preset != "minimal" else 0
    footer_h = 60 if preset != "minimal" else 40
    W = qr_img.width + pad * 2
    H = qr_img.height + pad * 2 + header_h + footer_h

    if preset == "modern":
        bg = (245, 247, 252)
        accent = (37, 99, 235)
    elif preset == "classic":
        bg = (255, 255, 255)
        accent = (17, 24, 39)
    else:  # minimal
        bg = (255, 255, 255)
        accent = (17, 24, 39)

    canvas = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(canvas)

    # Header bar
    if header_h:
        draw.rectangle([0, 0, W, header_h], fill=accent)
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", 28)
        except Exception:
            font = ImageFont.load_default()
        title = "QRIS"
        tw = draw.textlength(title, font=font)
        draw.text(((W - tw) / 2, (header_h - 30) / 2), title, fill="white", font=font)

    # QR box
    qx = pad
    qy = header_h + pad
    # Card behind QR for modern
    if preset == "modern":
        card = Image.new("RGB", (qr_img.width + 16, qr_img.height + 16), "white")
        canvas.paste(card, (qx - 8, qy - 8))
    canvas.paste(qr_img, (qx, qy))

    # Footer
    try:
        sfont = ImageFont.truetype("DejaVuSans.ttf", 18)
    except Exception:
        sfont = ImageFont.load_default()
    label = "Scan untuk membayar"
    lw = draw.textlength(label, font=sfont)
    ly = header_h + pad + qr_img.height + (footer_h - 18) // 2
    draw.text(((W - lw) / 2, ly), label, fill=accent, font=sfont)

    return canvas


def _apply_custom_frame(qr_img, frame_path: str):
    """Tempel QR di tengah gambar frame custom (jaga rasio & padding)."""
    from PIL import Image
    frame = Image.open(frame_path).convert("RGB")
    # Skalakan QR jadi ~60% dari sisi terpendek frame
    target = int(min(frame.size) * 0.6)
    qr = qr_img.resize((target, target), Image.LANCZOS)
    fx = (frame.width - target) // 2
    fy = (frame.height - target) // 2
    frame.paste(qr, (fx, fy))
    return frame


def generate_qris_image(
    payload: str,
    out_path: str = "/tmp/qris_dynamic.png",
    frame: str = "none",
    size: str = "small",
) -> str:
    """Generate gambar QRIS. Support frame preset (classic/modern/minimal) atau URL frame custom."""
    from PIL import Image

    qr_img, cfg = _render_qr(payload, size=size)
    frame = (frame or "none").strip()

    final_img = qr_img
    if frame and frame != "none":
        if frame in _FRAME_PRESETS:
            final_img = _draw_preset_frame(qr_img, frame, cfg)
        else:
            # Anggap URL/path custom. /static/... → relatif; http(s) → download sementara.
            try:
                if frame.startswith("http://") or frame.startswith("https://"):
                    import httpx, uuid as _uuid
                    tmp = f"/tmp/qris_frame_{_uuid.uuid4().hex}.png"
                    r = httpx.get(frame, timeout=10)
                    with open(tmp, "wb") as f:
                        f.write(r.content)
                    final_img = _apply_custom_frame(qr_img, tmp)
                    try:
                        import os as _os
                        _os.remove(tmp)
                    except Exception:
                        pass
                else:
                    local = frame.lstrip("/")
                    final_img = _apply_custom_frame(qr_img, local)
            except Exception:
                # Fallback: kirim QR polos kalau frame gagal dibaca
                final_img = qr_img

    # Batasi ukuran max sesuai preset supaya tidak terlalu besar
    max_side = cfg["final"]
    if max(final_img.size) > max_side:
        ratio = max_side / max(final_img.size)
        final_img = final_img.resize(
            (int(final_img.width * ratio), int(final_img.height * ratio)),
            Image.LANCZOS,
        )

    final_img.save(out_path, format="PNG", optimize=True)
    return out_path
