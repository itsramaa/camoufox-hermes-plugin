#!/usr/bin/env bash
# Helper script to install OS-level dependencies required by Camoufox (Firefox)
set -e

echo "[camoufox] Verifying system libraries for Firefox/Camoufox..."

# 1. Try playwright install-deps if python is available
if command -v python3 >/dev/null 2>&1; then
    echo "[camoufox] Running 'python3 -m playwright install-deps firefox'..."
    if python3 -m playwright install-deps firefox; then
        echo "[camoufox] Browser dependencies successfully installed via Playwright."
        exit 0
    fi
fi

# 2. Try apt-get if running on Debian / Ubuntu
if [ -f /etc/debian_version ] && command -v apt-get >/dev/null 2>&1; then
    echo "[camoufox] Attempting installation via apt-get..."
    apt-get update
    apt-get install -y --no-install-recommends \
        libgtk-3-0t64 libgtk-3-0 libdbus-glib-1-2 libxtst6 xvfb \
        fonts-noto-color-emoji fonts-liberation || {
            echo "[camoufox] apt-get failed. Please ensure you have root or sudo privileges."
            exit 1
        }
    echo "[camoufox] System packages installed successfully."
    exit 0
fi

echo "[camoufox] Automatic installation not supported for this system."
echo "[camoufox] Please install Firefox system dependencies manually."
exit 1
