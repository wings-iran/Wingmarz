#!/bin/bash

# Marzban Admin Bot Installation Script

echo "🚀 Installing Marzban Admin Management Bot..."

# Check Python version
python_version=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "📋 Python version: $python_version"

if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3, 8) else 1)'; then
    echo "❌ Python 3.8+ is required"
    exit 1
fi

# Install dependencies
echo "📦 Installing dependencies..."
pip3 install -r requirements.txt

# Create environment file template
if [ ! -f .env ]; then
    echo "📝 Creating environment template..."
    cat > .env << EOL
# Telegram Bot Configuration (set via environment)
# BOT_TOKEN=your_telegram_bot_token_here

# Marzban Panel Configuration
MARZBAN_URL=https://your-marzban-panel.com
MARZBAN_USERNAME=admin
MARZBAN_PASSWORD=your_admin_password

# Sudo Admins (comma-separated user IDs)
SUDO_ADMINS=123456789,987654321

# Optional Configuration
MONITORING_INTERVAL=600
WARNING_THRESHOLD=0.8
DATABASE_PATH=bot_database.db
API_TIMEOUT=30
MAX_RETRIES=3
EOL
    echo "✅ Environment template created (.env)"
    echo "📝 Please edit .env file with your configuration"
else
    echo "⚠️  .env file already exists"
fi

# Create systemd service template
echo "🔧 Creating systemd service template..."
cat > marzban-admin-bot.service << EOL
[Unit]
Description=Marzban Admin Management Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
Environment=PATH=$(which python3)
EnvironmentFile=$(pwd)/.env
ExecStart=$(which python3) bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOL

echo "✅ Systemd service template created"
echo ""
echo "🔧 To install as system service:"
echo "   sudo cp marzban-admin-bot.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable marzban-admin-bot"
echo "   sudo systemctl start marzban-admin-bot"
echo ""
echo "📝 Don't forget to:"
echo "   1. Edit .env file with your configuration"
echo "   2. Create your Telegram bot with @BotFather"
echo "   3. Add your user ID to SUDO_ADMINS"
echo ""
echo "🚀 To run manually: python3 bot.py"
EOL