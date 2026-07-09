"""
Kurigram Session String Generator
Support: QR Code Login & 2FA Password

Jalankan: python generate_session.py
"""

import asyncio
import qrcode
import sys

try:
    from pyrogram import Client
    from pyrogram.errors import SessionPasswordNeeded
except ImportError:
    print("❌ Install dulu: pip install kurigram qrcode[pil]")
    sys.exit(1)


def print_qr_terminal(url: str):
    """Print QR code langsung di terminal."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


async def login_with_qr():
    """Login menggunakan QR Code scan dari HP."""
    print("\n" + "=" * 50)
    print("  📱 LOGIN VIA QR CODE")
    print("=" * 50)

    api_id = int(input("\nMasukkan API ID: "))
    api_hash = input("Masukkan API Hash: ")

    client = Client(
        name="session_gen_qr",
        api_id=api_id,
        api_hash=api_hash,
        in_memory=True,
    )

    await client.connect()

    try:
        # Request QR code login
        qr_login = await client.qr_login()

        print("\n📱 Scan QR Code di bawah ini dengan Telegram di HP kamu:")
        print("   Telegram → Settings → Devices → Link Desktop Device\n")

        print_qr_terminal(qr_login.url)

        print("\n⏳ Menunggu scan dari HP...")
        print("   (QR akan refresh otomatis jika expired)\n")

        # Wait for QR to be scanned, auto-refresh if expired
        while True:
            try:
                r = await qr_login.wait(timeout=30)
                break
            except asyncio.TimeoutError:
                # QR expired, recreate
                await qr_login.recreate()
                print("🔄 QR expired, generating ulang...\n")
                print_qr_terminal(qr_login.url)
                print("\n⏳ Menunggu scan...")

    except SessionPasswordNeeded:
        # Akun punya 2FA password
        print("\n🔐 Akun ini memiliki Two-Step Verification!")
        password = input("Masukkan 2FA Password: ")
        await client.check_password(password)
        print("✅ 2FA berhasil!")

    # Export session string
    session_string = await client.export_session_string()

    print("\n" + "=" * 50)
    print("✅ SESSION STRING BERHASIL DI-GENERATE!")
    print("=" * 50)

    me = await client.get_me()
    print(f"\n👤 Login sebagai: {me.first_name} (@{me.username or 'N/A'})")
    print(f"📞 Phone: +{me.phone_number or 'hidden'}")

    print(f"\n🔑 Session String:\n")
    print(session_string)

    print(f"\n" + "=" * 50)
    print("📋 Copy string di atas → paste ke .env")
    print("   SESSION_STRING=<string di atas>")
    print("=" * 50)

    await client.disconnect()
    return session_string


async def login_with_phone():
    """Login menggunakan nomor telepon + OTP."""
    print("\n" + "=" * 50)
    print("  📞 LOGIN VIA NOMOR TELEPON")
    print("=" * 50)

    api_id = int(input("\nMasukkan API ID: "))
    api_hash = input("Masukkan API Hash: ")
    phone = input("Masukkan nomor telepon (contoh: +6281234567890): ")

    client = Client(
        name="session_gen_phone",
        api_id=api_id,
        api_hash=api_hash,
        in_memory=True,
    )

    await client.connect()

    # Send code
    sent_code = await client.send_code(phone)
    print(f"\n📨 Kode OTP dikirim via {sent_code.type}")

    code = input("Masukkan kode OTP: ")

    try:
        await client.sign_in(phone, sent_code.phone_code_hash, code)
    except SessionPasswordNeeded:
        print("\n🔐 Akun ini memiliki Two-Step Verification!")
        password = input("Masukkan 2FA Password: ")
        await client.check_password(password)
        print("✅ 2FA berhasil!")

    # Export session string
    session_string = await client.export_session_string()

    print("\n" + "=" * 50)
    print("✅ SESSION STRING BERHASIL DI-GENERATE!")
    print("=" * 50)

    me = await client.get_me()
    print(f"\n👤 Login sebagai: {me.first_name} (@{me.username or 'N/A'})")

    print(f"\n🔑 Session String:\n")
    print(session_string)

    print(f"\n" + "=" * 50)
    print("📋 Copy string di atas → paste ke .env")
    print("   SESSION_STRING=<string di atas>")
    print("=" * 50)

    await client.disconnect()
    return session_string


async def main():
    print("=" * 50)
    print("  ⚡ Kurigram Session String Generator")
    print("  Support: QR Code & 2FA Password")
    print("=" * 50)

    print("\nPilih metode login:")
    print("  1. 📱 QR Code (Scan dari HP) — RECOMMENDED")
    print("  2. 📞 Nomor Telepon + OTP")
    print()

    choice = input("Pilihan (1/2): ").strip()

    if choice == "1":
        await login_with_qr()
    elif choice == "2":
        await login_with_phone()
    else:
        print("❌ Pilihan tidak valid!")
        return


if __name__ == "__main__":
    asyncio.run(main())
