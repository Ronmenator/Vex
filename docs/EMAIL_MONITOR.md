# Email Monitor System

An autonomous email filtering and assistant system that monitors multiple accounts, identifies spam, and drafts responses to promising emails.

## 🎯 Features

- 📧 **Multi-account support**: Gmail + Office 365 accounts
- 🗑️ **Automatic spam filtering**: Deletes obvious junk/spam
- 📝 **Smart reply drafting**: Generates thoughtful replies to interesting emails
- 📱 **Telegram notifications**: Real-time updates about interesting emails
- ⏰ **Scheduled checking**: Runs every 10 minutes
- 📊 **Metrics logging**: Tracks what was processed

## 🛠️ Prerequisites

```bash
# Python dependencies
pip install google-auth-oauthlib google-api-python-client msal
```

## 🔐 Configuration

### 1. Gmail OAuth Setup

**Option A: Chrome Session Export (Easiest)**

```bash
# Ensure browser-launcher is installed
pip install browser-launcher

# Set your Chrome user data directory
export CHROME_USER_DATA_DIR='~/Library/Application Support/Google/Chrome'  # macOS
# or
export CHROME_USER_DATA_DIR='C:\\Users\\YourName\\AppData\\Local\\Google\\Chrome'  # Windows

# Generate OAuth credentials
python3 -c "
import asyncio
from email.client import GmailClient

async def get_credentials():
    client = GmailClient('ronnie@ronniebarnard.com')
    await client._ensure_service()
    print('✅ Credentials saved to ~/.gmail_creds.json')

asyncio.run(get_credentials())
"
```

**Option B: Manual OAuth Flow**

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create OAuth 2.0 credentials or use exported browser session
3. Save credentials to `~/.gmail_creds.json`

### 2. Office 365 Setup

1. Create app registration at [Azure portal](https://portal.azure.com/#blade/Microsoft_AAD_AppRegistrations/applicationsListBlade)
2. Get:
   - Client ID
   - Client Secret
   - Tenant ID
3. Add to `.env` file (see example below)

### 3. Environment Variables

Create `.env` file:

```bash
# Copy from .env.email.example
cp .env.email.example .env

# Edit with your credentials
nano .env
```

Required keys:
```
TELEGRAM_BOT_TOKEN=your_bot_token
GMAIL_EMAIL=ronnie@ronniebarnard.com
GMAIL_CREDENTIALS_FILE=~/.gmail_creds.json

OFFICE365_EMAIL_FZZY=ronnie@fzzy.ai
OFFICE365_TENANT_FZZY=your_tenant_id
OFFICE365_CLIENT_ID_FZZY=your_client_id
OFFICE365_CLIENT_SECRET_FZZY=your_client_secret

# ... repeat for sopliance and infogility
```

## 🚀 Usage

### Start the Email Monitor

```bash
# Start everything (Telegram bot + Email monitor)
python email_monitor.py
```

The system will:
- ✅ Start Telegram bot for notifications
- ✅ Initialize all email accounts
- ✅ Begin checking for emails every 10 minutes
- 📱 Send Telegram notifications for interesting findings

### Manual Check

```python
from src.email.scheduler import EmailScheduler

scheduler = EmailScheduler(check_interval_minutes=60)
await scheduler.check_email()
```

## 📊 What Happens on Each Check

1. **Connect** to all configured email accounts
2. **Fetch** unread emails
3. **Analyze** each email using smart classification:
   - **SPAM**: Delete immediately (>=2 spam keywords)
   - **Archive**: Low confidence spam (1 spam keyword)
   - **INTERESTING**: High value content (>=2 interesting keywords or important domains)
   - **ROUTINE**: Not relevant (no action)

4. **Generate** replies for interesting emails (saves as draft)
5. **Notify** via Telegram for interesting emails

## 📝 Reply Drafting

For interesting emails, the system generates a thoughtful reply:
```
Hi {sender},

I received your email about: "{subject}"

Preview: {email_preview}

What specific action would you like from me? I can schedule a call, discuss a partnership, or help with the project mentioned.

Best regards,
Ronnie
```

Review and send drafts manually from your email client.

## 📈 Metrics

Metrics are logged to `/tmp/email_metrics.txt`:
```json
{
  "timestamp": "2025-03-20T10:30:00",
  "sources": ["gmail", "office365_fzzy"],
  "decision_counts": {"spam": 5, "interesting": 3, "routine": 12},
  "by_source": {
    "gmail": {"spam": 2, "interesting": 1},
    "office365_fzzy": {"spam": 3, "interesting": 2}
  }
}
```

## 🔧 Customization

### Spam Keywords

Edit in `src/email/manager.py`:
```python
SPAM_KEYWORDS = [
    'one time offer',
    'claim now',
    'winner',
    # ... add more
]
```

### Interesting Keywords

Edit in `src/email/manager.py`:
```python
INTERESTING_KEYWORDS = [
    'launch',
    'update',
    'feature',
    # ... add more
]
```

### Reply Style

Edit `src/email/manager.py::EmailProcessor._generate_reply()`

### Check Interval

Edit in `.env`:
```bash
EMAIL_CHECK_INTERVAL_MINUTES=5
```

## 📱 Telegram Commands

After starting:
- `/start` - Shows stats
- `/clear` - Resets conversation
- `/status` - Shows current configuration

## ⚠️ Troubleshooting

**"Gmail credentials not found"**
- Ensure Chrome user data directory is set correctly
- Try running the Chrome export script again

**"Office 365 token acquisition failed"**
- Verify tenant_id, client_id, and client_secret
- Check that tenant id matches app domain
- Revoke and regenerate app credentials if needed

**"No emails detected every 10 minutes"**
- Check your email accounts
- Verify accounts have new unread emails
- Enable debug logging: `EMAIL_LOG_LEVEL=DEBUG`

## 📜 License

Part of Vex System - Ultimate AI AGI Reborn