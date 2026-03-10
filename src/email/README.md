# Email Monitor Module

Autonomous email filtering and assistant system for Vex.

## Quick Start

```bash
# 1. Setup Gmail credentials
./gmail_auth_setup.sh

# 2. Configure Office 365 apps in Azure portal
#    Save credentials to .env file

# 3. Start monitoring
python email_monitor.py
```

## What It Does

- ✅ Monitors Gmail and Office 365 accounts
- 🗑️ Auto-deletes spam (2+ spam keywords)
- 📝 Drafts replies to interesting emails
- 📱 Sends Telegram notifications
- ⏰ Runs every 10 minutes

See `docs/EMAIL_MONITOR.md` for full documentation.