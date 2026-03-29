#!/bin/bash
set -e

echo "=========================================="
echo "  YT Cutter Pro - Starting Setup"
echo "=========================================="

cd "$(dirname "$0")"

# Install system deps
echo "[1/4] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg python3-pip python3-venv > /dev/null 2>&1

# Create venv
echo "[2/4] Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate

# Install Python deps
echo "[3/4] Installing Python packages..."
pip install -q -r requirements.txt

# Download & setup cloudflared
echo "[4/4] Setting up Cloudflare Tunnel..."
if [ ! -f ./cloudflared ]; then
    wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -O cloudflared
    chmod +x cloudflared
fi

# Start Flask app in background
echo ""
echo "Starting web application on port 8080..."
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