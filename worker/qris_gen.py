"""Dynamic QRIS payload generator + decoder (EMVCo standard).

- decode_qris_from_image: baca payload EMVCo dari gambar QRIS statis (pyzbar).
- build_dynamic_qris: ubah QRIS statis -> dinamis dgn nominal (recompute CRC).

UPDATE 2026-07-07: Dynamic QRIS sekarang STRICT hanya terima angka penuh murni.
Short format (5k, 5K, 10rb, 25.000, Rp10000) DITOLAK total.

UI toggle 'Support Short Amount' sudah tidak berpengaruh lagi karena enforcement dilakukan di backend.
"""

import qrcode


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
    t = str(text or "").strip()
    if not t.isdigit():
        raise ValueError("Format nominal tidak valid. Gunakan angka penuh, contoh: /qris 10000")
    amount_int = int(t)
    if amount_int <= 0:
        raise ValueError("Nominal harus lebih dari 0")
    return amount_int


def _parse_tlv(s: str):
    out = []
    i = 0
    n = len(s)
    while i + 4 <= n:
        tag = s[i:i + 2]
        length = int(s[i + 2:i + 4])
        val = s[i + 4:i + 4 + length]
        out.append((tag, val))
        i += 4 + length
    return out


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
            return data
    # fallback: kembalikan hasil pertama
    return results[0].data.decode("utf-8", "ignore").strip()


def build_dynamic_qris(base_payload: str, amount) -> str:
    """Bangun payload QRIS dinamis dari payload statis + nominal.

    amount boleh int/float/string.
    SEMUA path WAJIB lewat parse_amount() untuk validasi digit murni.
    TIDAK PERNAH int(amount) sebelum validasi isdigit.
    Short format otomatis ditolak oleh parse_amount.
    """
    base = (base_payload or "").strip().replace("\n", "").replace(" ", "")
    if not base:
        raise ValueError("Base QRIS payload belum diatur")

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
    for tag, val in _parse_tlv(base):
        data[tag] = val

    data["01"] = "12"            # dynamic
    data.pop("63", None)          # drop old CRC
    data["54"] = str(amount_int)  # transaction amount

    body = ""
    for tag in sorted(data.keys(), key=lambda x: int(x)):
        val = data[tag]
        body += tag + str(len(val)).zfill(2) + val
    body += "6304"
    return body + _crc16(body)


def generate_qris_image(payload: str, out_path: str = "/tmp/qris_dynamic.png") -> str:
    img = qrcode.make(payload)
    img.save(out_path)
    return out_path
