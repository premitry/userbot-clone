<div align="center">

# ⚡ Telegram Userbot Dashboard

Web-based Telegram Userbot Dashboard built with **FastAPI** and **Kurigram**.

Kelola banyak akun Telegram, bikin custom command, jadwalkan Auto Share campaign, dan pantau semuanya dari dashboard web modern.

![Python](https://img.shields.io/badge/Python-3.10+-3776ab?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)

</div>

---

## 📑 Table of Contents

- [✨ Features](#-features)
- [📋 Prerequisites](#-prerequisites)
- [🚀 Local Installation](#-local-installation)
- [🔐 Login and Security](#-login-and-security)
- [🌐 Deploy VPS Ubuntu](#-deploy-vps-ubuntu)
- [⚙️ Setup Systemd Service](#️-setup-systemd-service)
  - [🌍 Setup Nginx Reverse Proxy](#-setup-nginx-reverse-proxy)
  - [🧩 Alternatif: Setup Caddy (SSL Otomatis)](#-alternatif-setup-caddy-ssl-otomatis)
  - [🔒 Setup SSL HTTPS](#-setup-ssl-https)
- [🔁 Update Project](#-update-project)
- [🛠️ Management Command](#️-management-command)
- [📱 Add Telegram Account](#-add-telegram-account)
- [💬 Messages (Custom Command)](#-messages-custom-command)
- [📢 Auto Share Campaign](#-auto-share-campaign)
- [⚙️ Settings](#️-settings)
- [📡 REST API](#-rest-api)
- [📂 Project Structure](#-project-structure)
- [🩺 Troubleshooting](#-troubleshooting)
- [🧰 Tech Stack](#-tech-stack)
- [🗺️ Roadmap](#️-roadmap)
- [📄 License](#-license)

---

## ✨ Features

- 📱 Multi Telegram Account
- 📷 QR Code Login (QR di-generate di server — tanpa library eksternal)
- 🔐 2FA Support
- 💬 **Custom Command Manager (Messages)** — bikin command sendiri (`/pay`, `/share`, `/qris`, dll)
- 🧾 **Dynamic QRIS** — QRIS dengan nominal otomatis (`/qris 5000`, `/qris 5k`, `/qris 25.000`)
- 📷 Upload media (foto/video/dokumen) & Album multi-media
- ↗️ Forward / Copy postingan channel
- 📢 **Auto Share Campaign** — kirim Message otomatis ke banyak grup + delay antar grup
- ⏰ Cron Scheduler
- 👥 Group Synchronization
- 🔑 Ganti username & password langsung dari dashboard
- 📊 Dashboard & Statistics
- 🛡️ FloodWait Auto Retry
- 🔄 Auto-migrasi database (kolom baru ditambah otomatis, tanpa reset DB)
- 🌙 Dark Mode

---

## 📋 Prerequisites

- **Python 3.10+**
- **Telegram API credentials** (`API_ID` & `API_HASH`) — dapatkan gratis di [my.telegram.org](https://my.telegram.org):
  1. Login dengan nomor Telegram kamu
  2. Buka **API development tools**
  3. Buat app baru → salin **api_id** dan **api_hash**
- **Akun Telegram** yang mau dijadikan userbot (boleh lebih dari satu)
- _(Opsional, untuk produksi)_ **VPS Ubuntu** + domain untuk deploy

> `API_ID` dan `API_HASH` sama untuk semua akun — cukup satu pasang.

---

## 🚀 Local Installation

### 1. Clone Repository

```bash
git clone https://github.com/premitry/userbot-clone.git
cd userbot
```

### 2. Create Virtual Environment

Linux / macOS:

```bash
python3 -m venv venv
source venv/bin/activate
```

Windows (PowerShell):

```powershell
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

> Catatan: nama paket pip adalah **`kurigram`**, tapi tetap di-import sebagai `pyrogram` (Kurigram adalah fork Pyrogram).

### 4. Configure

```bash
cp .env.example .env
```

Edit `.env`, minimal isi:

```env
API_ID=123456
API_HASH=xxxxxxxxxxxxxxxxxxxxxxxx
SECRET_KEY=ganti-dengan-string-random-panjang
```

### 5. Run

```bash
python main.py
```

Buka dashboard:

```text
http://localhost:8000
```

---

## 🔐 Login and Security

Login dashboard **disimpan di database** (tabel `User`), **bukan** di file `.env`.

Saat pertama kali dijalankan, aplikasi otomatis membuat user default:

| Username | Password   |
|----------|------------|
| `admin`  | `admin123` |

> ⚠️ **WAJIB ganti password default sebelum dipakai publik / produksi!**

### Ganti Username / Password

Ada dua cara:

1. **Dari dashboard** — buka menu **Settings**, tersedia form ganti username dan ganti password (butuh password lama).
2. **Dari CLI** (mis. kalau lupa password) — gunakan `reset_password.py`:

```bash
# interaktif (akan menanyakan password baru)
python reset_password.py

# atau langsung
python reset_password.py admin passwordbaru123
```

Kalau berjalan di VPS/systemd, aktifkan virtual environment dulu:

```bash
cd /root/userbot
source venv/bin/activate
python reset_password.py
```

Script ini juga bisa membuat user baru jika username yang dimasukkan belum ada.

### Tentang `SECRET_KEY`

`SECRET_KEY` di `.env` **bukan** password login — ini kunci untuk menandatangani token JWT (sesi login). Tetap wajib diganti dengan string acak yang panjang agar sesi login aman. Jika `SECRET_KEY` diubah, semua sesi login lama otomatis ikut logout.

---

## 🌐 Deploy VPS Ubuntu

Panduan ini menggunakan **Ubuntu 20.04 / 22.04 / 24.04**.

### 1. Update Server

```bash
sudo apt update && sudo apt upgrade -y
```

### 2. Install Dependency

```bash
sudo apt install -y python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx
```

### 3. Clone Project

```bash
cd /root
git clone https://github.com/premitry/userbot-clone.git
cd userbot
```

### 4. Setup Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5. Setup Environment

```bash
cp .env.example .env
nano .env
```

Isi minimal:

```env
API_ID=123456
API_HASH=your_api_hash_here
SECRET_KEY=change_this_random_secret
APP_HOST=127.0.0.1
APP_PORT=8000
DEBUG=false
```

### 6. Test Run

```bash
python main.py
```

Jika berhasil, buka:

```text
http://YOUR_SERVER_IP:8000
```

Tekan `CTRL + C` untuk stop, lalu lanjut setup service.

---

## ⚙️ Setup Systemd Service

### 1. Buat Service

```bash
sudo nano /etc/systemd/system/userbot.service
```

Isi:

```ini
[Unit]
Description=Telegram Userbot Dashboard
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/userbot
Environment="PATH=/root/userbot/venv/bin"
ExecStart=/root/userbot/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 2. Jalankan Service

```bash
sudo systemctl daemon-reload
sudo systemctl enable userbot
sudo systemctl start userbot
```

### 3. Cek Status

```bash
sudo systemctl status userbot
```

Cek log real-time:

```bash
sudo journalctl -u userbot -f
```

---

## 🌍 Setup Nginx Reverse Proxy

### 1. Buat Config Nginx

```bash
sudo nano /etc/nginx/sites-available/userbot
```

Isi:

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Ganti `yourdomain.com` dengan domain Anda.

> Header `Upgrade` & `Connection` wajib ada agar QR Code login (WebSocket) berfungsi di belakang Nginx.
> `client_max_body_size 50M;` diperlukan agar upload media (foto/video/dokumen) tidak ditolak Nginx.

### 2. Aktifkan Config

```bash
sudo ln -sf /etc/nginx/sites-available/userbot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

## 🔒 Setup SSL HTTPS

Pastikan domain sudah mengarah ke IP VPS, lalu jalankan:

```bash
sudo certbot --nginx -d yourdomain.com
```

Cek auto-renew SSL:

```bash
sudo certbot renew --dry-run
```

---

## 🧩 Alternatif: Setup Caddy (SSL Otomatis)

Kalau kamu tidak mau ribet dengan Nginx + Certbot, pakai **Caddy** — reverse proxy modern yang otomatis mengurus SSL Let's Encrypt tanpa konfigurasi tambahan.

> **Pilih salah satu**: Nginx **ATAU** Caddy — jangan dua-duanya (bentrok di port 80/443).

### 1. Install Caddy

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | \
  sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | \
  sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install -y caddy
```

### 2. Pastikan Domain Sudah Pointing ke VPS

Di registrar domain (Cloudflare / Namecheap / dll), tambahkan **A record**:

| Type | Name | Value             | TTL  |
|------|------|-------------------|------|
| A    | @    | `<IP VPS kamu>`   | Auto |
| A    | www  | `<IP VPS kamu>`   | Auto |

Cek propagasi: `dig yourdomain.com +short` — harus muncul IP VPS.

> **Cloudflare user**: matikan dulu proxy (awan orange → abu-abu) saat pertama kali issue SSL. Setelah aktif, boleh dinyalakan lagi.

### 3. Buat Caddyfile

Sudah ada template siap pakai di repo: **`Caddyfile.example`**. Copy ke lokasi resmi Caddy:

```bash
sudo cp Caddyfile.example /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile   # ganti "yourdomain.com" dengan domain kamu
```

Isi minimal Caddyfile:

```caddy
yourdomain.com {
    reverse_proxy 127.0.0.1:8000 {
        header_up Host              {host}
        header_up X-Real-IP         {remote_host}
        header_up X-Forwarded-For   {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }

    request_body {
        max_size 50MB
    }

    encode gzip zstd
}
```

> `request_body { max_size 50MB }` wajib supaya upload media (foto/video/QRIS) tidak ditolak.
> Caddy otomatis handle WebSocket (untuk QR Code login) tanpa header tambahan.

### 4. Buka Firewall & Reload Caddy

```bash
sudo ufw allow 80,443/tcp
sudo systemctl reload caddy
sudo systemctl enable caddy
```

Cek status:

```bash
sudo systemctl status caddy
sudo journalctl -u caddy -f    # tail log realtime
```

### 5. Selesai — Buka Browser

Kunjungi `https://yourdomain.com` — SSL sudah aktif otomatis, tidak perlu certbot terpisah.

### Update Config Setelah Edit

```bash
sudo systemctl reload caddy    # reload tanpa downtime
# atau kalau ada error konfigurasi:
sudo caddy validate --config /etc/caddy/Caddyfile
```

---



## 🔁 Update Project

```bash
cd /root/userbot
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart userbot
```

> Kolom database baru ditambahkan otomatis saat start (auto-migrate), jadi **tidak perlu menghapus `userbot.db` atau login ulang akun**. Perhatikan log `🔧 Migrasi: tambah kolom ...` saat pertama kali restart setelah update.

---

## 🛠️ Management Command

Restart app:

```bash
sudo systemctl restart userbot
```

Stop app:

```bash
sudo systemctl stop userbot
```

Start app:

```bash
sudo systemctl start userbot
```

Lihat log:

```bash
sudo journalctl -u userbot -f
```

Restart Nginx:

```bash
sudo systemctl restart nginx
```

Reset password login:

```bash
source venv/bin/activate
python reset_password.py
```

---

## 📱 Add Telegram Account

Metode login yang didukung (menu **Accounts**):

- **QR Code** — QR di-generate di sisi server dan tampil sebagai gambar, tinggal scan dari Telegram HP (Settings → Devices → Link Desktop Device). Dilengkapi animasi loading saat proses.
- **Phone Number + OTP** — dengan dukungan 2FA.
- **Session String** — generate lewat CLI:

```bash
python generate_session.py
```

---

## 💬 Messages (Custom Command)

Menu **Messages** adalah manajer custom command yang dipakai **langsung saat kamu mengetik command di chat Telegram mana pun** (bukan dikirim ke grup dari dashboard). Command dieksekusi di chat tempat kamu mengetiknya.

Setiap Message punya konfigurasi:

| Field | Keterangan |
|-------|------------|
| **Command** | Trigger, mis. `/pay`, `/qris` |
| **Name** | Nama/label command |
| **Type** | `Text`, `Photo`, `Video`, `Document`, `Album`, `Forward Channel`, `Copy Channel`, `Dynamic QRIS` |
| **Action** | `Edit command message`, `Delete command then send`, `Delete command then forward` |
| **Content / Caption** | Isi teks atau caption media |
| **Media** | URL atau upload file (Album: satu URL per baris) |
| **Channel Post URL** | Untuk Forward/Copy Channel |
| **Active** | Aktif/nonaktif |

Contoh setup:

- **`/pay`** → Type `Text`, Action `Edit command message`, isi template pembayaran.
- **`/share`** → Type `Forward Channel`, Action `Delete command then forward`, isi Channel Post URL.
- **`/qris`** → Type `Dynamic QRIS`, Action `Delete command then send`. Base payload QRIS diisi di **Settings**. Mendukung nominal: `/qris 5000`, `/qris 5k`, `/qris 25.000`.

---

## 📢 Auto Share Campaign

Menu **Auto Share** untuk mengirim sebuah Message secara otomatis ke banyak grup sesuai jadwal.

Alur membuat campaign:

1. **Pilih Message** yang mau dikirim.
2. **Pilih target grup** (bisa banyak sekaligus — sync grup dulu kalau kosong).
3. **Set jadwal** dengan cron expression.
4. **Set delay** (detik) antar grup untuk menghindari FloodWait.
5. Simpan campaign.

Cron format:

```text
* * * * *
│ │ │ │ │
│ │ │ │ └── Day of week
│ │ │ └──── Month
│ │ └────── Day
│ └──────── Hour
└────────── Minute
```

Example:

```text
0 9 * * *       # tiap hari jam 09:00
0 */2 * * *     # tiap 2 jam
*/30 * * * *    # tiap 30 menit
```

---

## ⚙️ Settings

Menu **Settings** menyediakan:

- **Base payload QRIS** — dipakai oleh command bertipe Dynamic QRIS untuk menghasilkan QRIS dengan nominal.
- **Ganti username** — butuh password lama.
- **Ganti password** — butuh password lama.

---

## 📡 REST API

```text
POST /api/auth/login
GET  /api/auth/me
GET  /api/accounts/
POST /api/accounts/send-code
POST /api/accounts/verify-code
POST /api/accounts/verify-2fa
POST /api/accounts/add-session
WS   /api/accounts/qr-login
GET  /api/messages/
POST /api/messages/
POST /api/messages/upload
PUT  /api/messages/{id}
PUT  /api/messages/{id}/toggle
DELETE /api/messages/{id}
GET  /api/schedules/
POST /api/schedules/
PUT  /api/schedules/{id}/toggle
DELETE /api/schedules/{id}
GET  /api/groups/
POST /api/groups/sync
GET  /api/settings/
PUT  /api/settings/
POST /api/settings/change-password
POST /api/settings/change-username
GET  /api/dashboard/stats
```

Swagger docs:

```text
http://localhost:8000/docs
```

---

## 📂 Project Structure

```text
userbot/
├── main.py               # Entry point FastAPI + lifespan
├── config.py             # Konfigurasi dari .env
├── auth.py               # JWT auth, hash password, default user
├── database.py           # SQLAlchemy engine + init_db + auto-migrate
├── models.py             # Model DB (User, TelegramAccount, Message, Schedule, dll)
├── schemas.py            # Pydantic schemas
├── generate_session.py   # CLI generator session string
├── reset_password.py     # CLI ganti/reset password login
├── requirements.txt
├── .env.example
├── routers/              # Endpoint FastAPI
│   ├── auth_router.py
│   ├── accounts.py        # login QR/OTP/session (QR image server-side)
│   ├── messages.py        # custom command manager + upload media
│   ├── schedules.py       # Auto Share campaign
│   ├── groups.py
│   ├── settings.py        # QRIS payload, ganti username/password
│   └── dashboard.py       # halaman + stats
├── worker/              # Telegram client & background jobs
│   ├── client.py          # Multi-account client manager
│   ├── command_handler.py # eksekusi custom command saat diketik di chat
│   ├── message_sender.py  # kirim Message ke chat (dipakai Auto Share)
│   ├── scheduler.py       # APScheduler (cron) untuk campaign
│   ├── qris_gen.py        # generator Dynamic QRIS (CRC16 + nominal)
│   ├── flood_handler.py   # FloodWait auto-retry
│   └── commands/          # implementasi command legacy
│       ├── share.py
│       ├── pay.py
│       └── qris.py
├── templates/           # Jinja2 templates
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── accounts.html
│   ├── messages.html
│   ├── schedules.html     # Auto Share
│   ├── queue.html
│   ├── logs.html
│   ├── settings.html
│   └── groups.html
└── static/              # Asset (di-mount di /static)
    ├── css/app.css
    ├── js/app.js
    └── uploads/           # hasil upload media
```

---

## 🩺 Troubleshooting

**`ModuleNotFoundError: No module named 'pyrogram'`**
> Jalankan `pip install -r requirements.txt`. Kurigram menyediakan namespace `pyrogram`, jadi import `from pyrogram import Client` memang benar.

**`AttributeError: module 'bcrypt' has no attribute '__about__'`**
> Terjadi kalau `bcrypt >= 4.1` dipakai dengan `passlib 1.7.4`. Pastikan pakai `bcrypt==4.0.1` (sudah dipin di `requirements.txt`).

**`jinja2.exceptions.TemplateSyntaxError`**
> Biasanya karena file template terpotong atau ada blok `{% block %}` yang tidak ditutup. Pastikan file template lengkap.

**Lupa / tidak bisa login**
> Jalankan `python reset_password.py` untuk set ulang password. Login default awal: `admin` / `admin123`.

**Worker Telegram tidak jalan / `API_ID atau API_HASH kosong`**
> Isi `API_ID` dan `API_HASH` di `.env` (dapat dari https://my.telegram.org).

**Port 8000 sudah dipakai**
> Ganti `APP_PORT` di `.env`, lalu restart aplikasi.

**QR Code login gagal di belakang Nginx**
> Pastikan header `Upgrade` dan `Connection "upgrade"` ada di config Nginx (WebSocket).

**Upload media gagal / `413 Request Entity Too Large`**
> Tambahkan `client_max_body_size 50M;` di config Nginx, lalu `sudo systemctl restart nginx`.

**Sync grup tidak memunculkan grup**
> Pastikan akun sudah connected (status hijau di menu Accounts) sebelum menekan Sync.

**Kolom baru tidak muncul setelah update**
> Auto-migrate jalan saat start; cek log `🔧 Migrasi: tambah kolom ...`. Kalau perlu, restart service sekali lagi.

---

## 🧰 Tech Stack

- Python 3.10+
- FastAPI
- Kurigram
- SQLAlchemy
- APScheduler
- Jinja2
- TailwindCSS
- qrcode (QR image server-side)

---

## 🗺️ Roadmap

- [x] Custom Command Manager (Messages)
- [x] Dynamic QRIS
- [x] File Upload
- [x] In-dashboard password change
- [x] Auto Share multi-target campaign
- [ ] Multi User
- [ ] CSV Export
- [ ] Plugin System
- [ ] Webhook Notification
- [ ] Album campur foto + video

---

## 📄 License

MIT License

---

<div align="center">

Made with ❤️ by Premitry

⭐ Star this repository if you find it useful.

</div>
