#!/usr/bin/env bash
#
# setup.sh — install semua dependency Userbot (system apt + Python pip).
# Jalankan sekali sebelum menjalankan bot:
#
#   bash setup.sh
#
# Setelah selesai, cukup jalankan:
#
#   python main.py
#

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[setup]${NC} $1"; }
warn()  { echo -e "${YELLOW}[setup]${NC} $1"; }
error() { echo -e "${RED}[setup]${NC} $1"; }

cd "$(dirname "$0")"

# ────────────────────────────────────
# 1. System dependencies (apt)
#    - libzbar0 : dibutuhkan pyzbar untuk decode gambar QRIS
# ────────────────────────────────────
info "Memasang system dependencies..."

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    fi
fi

if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update -y
    $SUDO apt-get install -y libzbar0 python3-pip python3-venv python3-full
elif command -v dnf >/dev/null 2>&1; then
    $SUDO dnf install -y zbar python3-pip
elif command -v yum >/dev/null 2>&1; then
    $SUDO yum install -y zbar python3-pip
elif command -v apk >/dev/null 2>&1; then
    $SUDO apk add --no-cache zbar py3-pip
else
    warn "Package manager tidak dikenali. Install manual: libzbar0 (atau zbar) + python3-pip."
fi

# ────────────────────────────────────
# 2. Python dependencies (pip)
# ────────────────────────────────────
info "Memasang Python dependencies dari requirements.txt..."

if command -v pip >/dev/null 2>&1; then
    PIP="pip"
elif command -v pip3 >/dev/null 2>&1; then
    PIP="pip3"
else
    PIP="python3 -m pip"
fi

# PEP 668: sebagian distro (Debian 12 / Ubuntu 24, Python 3.12+) menandai
# environment sebagai "externally managed" sehingga pip system-wide ditolak.
# Tambahkan --break-system-packages HANYA jika flag itu didukung pip.
BSP=""
if $PIP install --help 2>/dev/null | grep -q -- "--break-system-packages"; then
    BSP="--break-system-packages"
    warn "Environment externally-managed terdeteksi — memakai --break-system-packages."
fi

$PIP install --upgrade pip $BSP
$PIP install -r requirements.txt $BSP

# ────────────────────────────────────
# Selesai
# ────────────────────────────────────
echo ""
info "Setup selesai! \xE2\x9C\x85"
echo ""
echo -e "${GREEN}Sekarang jalankan bot dengan:${NC}"
echo ""
echo "    python main.py"
echo ""
