#!/usr/bin/env python3
"""
Example script showing how to run the Marzban Admin Bot
with custom configuration for development/testing
"""

import os
import asyncio

# Set environment variables for testing
# In production, these should be set in the environment or .env file
os.environ.update({
    'BOT_TOKEN': 'YOUR_BOT_TOKEN_HERE',  # Replace with actual token
    'MARZBAN_URL': 'https://your-marzban-panel.com',  # Replace with actual URL
    'MARZBAN_USERNAME': 'admin',  # Replace with actual username
    'MARZBAN_PASSWORD': 'your_password',  # Replace with actual password
    'SUDO_ADMINS': '123456789,987654321',  # Replace with actual user IDs
    'MONITORING_INTERVAL': '300',  # 5 minutes for testing
    'WARNING_THRESHOLD': '0.8',
    'DATABASE_PATH': 'test_bot.db'
})

# Now import and run the bot
from bot import main

if __name__ == "__main__":
    print("🚀 Starting Marzban Admin Bot Example")
    print("📝 Make sure to configure your environment variables!")
    print("🔧 This is an example - edit the variables above for your setup")
    print()
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"\n💥 Error: {e}")
        print("📝 Please check your configuration and try again")