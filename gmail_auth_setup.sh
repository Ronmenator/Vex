#!/bin/bash
"""Setup script for Gmail OAuth credentials."""

echo "📧 Gmail OAuth Setup for Email Monitor"
echo "========================================"

# Instructions for setting up Gmail OAuth token
echo "
REQUIREMENTS: A Chrome browser where you've already logged in to your Gmail account

1️⃣  Install browser-launcher package:
    pip install browser-launcher

2️⃣  Export your Chrome user data directory:
    # macOS/Linux
    export CHROME_USER_DATA_DIR='~/Library/Application Support/Google/Chrome'

    # Windows
    export CHROME_USER_DATA_DIR='C:\\\\Users\\\\YourName\\\\AppData\\\\Local\\\\Google\\\\Chrome'

3️⃣  Run this script to get your Gmail API credentials:

    ./gmail_auth_setup.sh

This will open a Chrome browser session with Gmail, and you'll need to:
   - Grant OAuth permissions when prompted
   - Copy the generated credentials to ~/.gmail_creds.json
"

# Ask user if they want to generate credentials now
read -p "➡️  Would you like to generate Gmail credentials now? (y/n) " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
    python3 -c "
import asyncio
from email.client import GmailClient

async def get_credentials():
    client = GmailClient('ronnie@ronniebarnard.com')
    await client._ensure_service()
    print('✅ Gmail service initialized successfully!')
    print('   Credentials saved to ~/.gmail_creds.json')

asyncio.run(get_credentials())
"
fi

echo "
📝 Next steps:

1. Complete the Gmail OAuth flow when prompted
2. Set the credentials file path in .env:
   GMAIL_EMAIL=ronnie@ronniebarnard.com
   GMAIL_CREDENTIALS_FILE=~/.gmail_creds.json

3. Start the email monitor:
   python email_monitor.py

📱 Notifications will be sent to Telegram!