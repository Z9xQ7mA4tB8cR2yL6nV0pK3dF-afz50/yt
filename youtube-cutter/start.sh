#!/bin/bash
set -e

echo "=========================================="
echo "  YT Cutter Pro - Starting Setup"
echo "=========================================="

cd "$(dirname "$0")"

# Install system deps
echo "[1/5] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg python3-pip python3-venv curl nodejs > /dev/null 2>&1

# Create venv
echo "[2/5] Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate

# Install Python deps
echo "[3/5] Installing Python packages..."
pip install -q -r requirements.txt

# Force upgrade yt-dlp to absolute latest nightly (fixes YouTube blocks)
echo "[3.5/5] Upgrading yt-dlp to latest nightly..."
pip install -q --force-reinstall https://github.com/yt-dlp/yt-dlp/archive/master.tar.gz
pip install -q quickjs

# Verify yt-dlp works
echo "yt-dlp version: $(python3 -m yt_dlp --version)"


echo "--- ENV DEBUG ---"
which node && node --version || echo "node NOT in PATH"
echo "PATH=$PATH"
python3 -c "import quickjs; print('quickjs: OK')" 2>&1 || echo "quickjs: FAILED"
pip install bgutil-ytdlp-pot-provider 2>&1 | tail -5

echo "Setting up bgutil PO Token server scripts..."
git clone https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git ~/bgutil-ytdlp-pot-provider
cd ~/bgutil-ytdlp-pot-provider/server
npm install 2>&1 | tail -5
npx tsc 2>&1 | tail -5
ls -la build/ 2>&1 | head -5
cd -

echo "--- END ENV DEBUG ---"


# Quick test
echo "Quick test fetching video info..."

echo "--- yt-dlp debug test ---"
python3 -m yt_dlp --verbose --dump-json --no-download "--extractor-args", "youtube:player_client=web;po_token_provider=bgutil:script-node", "https://www.youtube.com/watch?v=jNQXAC9IVRw" 2>&1 | tail -30
echo "--- end debug test ---"

# Download & setup cloudflared
echo "[4/5] Setting up Cloudflare Tunnel..."
if [ ! -f ./cloudflared ]; then
    wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared
    chmod +x cloudflared
fi

# Start Flask app in background
echo "[5/5] Starting web application on port 8080..."
python3 app.py &
APP_PID=$!
sleep 3

# Start cloudflared tunnel
echo "Starting Cloudflare Tunnel..."
echo ""
./cloudflared tunnel --url http://localhost:8080 2>&1 | tee /tmp/cloudflared.log &
TUNNEL_PID=$!

# Wait for tunnel URL
echo "Waiting for tunnel URL..."
for i in $(seq 1 30); do
    TUNNEL_URL=$(grep -oP 'https://[\w-]+\.trycloudflare\.com' /tmp/cloudflared.log | head -1)
    if [ -n "$TUNNEL_URL" ]; then
        break
    fi
    sleep 2
done

echo ""
echo "=========================================="
echo "  ✅ YT CUTTER PRO IS READY!"
echo "=========================================="
echo ""
echo "  🌐 Web App URL: $TUNNEL_URL"
echo ""
echo "=========================================="
echo ""

# Keep alive
wait $APP_PID
