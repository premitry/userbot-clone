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


def _size_presets():
    """Preset ukuran dari environment/config; restart service untuk menerapkan."""
    from config import settings

    return {
        "small": {"box": 6, "border": 2, "final": settings.QRIS_SIZE_SMALL},
        "medium": {"box": 8, "border": 3, "final": settings.QRIS_SIZE_MEDIUM},
        "large": {"box": 10, "border": 4, "final": settings.QRIS_SIZE_LARGE},
    }


def _resize_to_width_limit(img, target_width: int, max_width: int):
    """Resize proporsional: pilih preset, lalu batasi lebar maksimum untuk Telegram."""
    from PIL import Image

    width = max(1, int(target_width or img.width))
    limit = max(1, int(max_width or width))
    final_width = min(width, limit)
    if img.width == final_width:
        return img
    ratio = final_width / img.width
    return img.resize(
        (final_width, max(1, int(img.height * ratio))),
        Image.LANCZOS,
    )


def _render_qr(payload: str, size: str = "small"):
    """Render QR code sebagai PIL.Image RGB dengan ukuran yg lebih kecil dari default."""
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M

    presets = _size_presets()
    cfg = presets.get(size or "small", presets["small"])
    qr = qrcode.QRCode(
        error_correction=ERROR_CORRECT_M,
        box_size=cfg["box"],
        border=cfg["border"],
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img, cfg


def generate_qris_image(
    payload: str,
    out_path: str = "/tmp/qris_dynamic.png",
    frame: str = "none",
    size: str = "small",
) -> str:
    """Generate gambar QRIS polos. Parameter `frame` sudah tidak dipakai (dipertahankan
    untuk kompatibilitas call-site lama). Ukuran akhir gambar dipaksa mengecil sesuai
    preset supaya di Telegram tidak muncul kegedean.
    """
    from config import settings

    qr_img, cfg = _render_qr(payload, size=size)
    qr_img = _resize_to_width_limit(qr_img, cfg["final"], settings.QRIS_MAX_IMAGE_WIDTH)

    qr_img.save(out_path, format="PNG", optimize=True)
    return out_path

