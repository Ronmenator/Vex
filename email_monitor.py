"""Startup script to launch the email monitor agent."""

import asyncio
import logging
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from telegram.bot import run_bot
from email.scheduler import run_scheduler

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


async def start_all():
    """Start Vex + Email monitor together."""
    logger.info("="*60)
    logger.info("🚀 Vex System Starting")
    logger.info("="*60)
    logger.info("✅ TelegramBot: Ready")
    logger.info("📧 EmailMonitor: Ready")
    logger.info("="*60)

    # Start both asynchronously
    telegram_task = asyncio.create_task(_run_telegram())
    email_task = asyncio.create_task(_run_email_monitor())

    # Wait for interruption
    try:
        await asyncio.gather(telegram_task, email_task)
    except asyncio.CancelledError:
        pass


async def _run_telegram():
    """Run Telegram bot."""
    from telegram.bot import main as telegram_main
    await telegram_main()


async def _run_email_monitor():
    """Run email monitor scheduler."""
    from email.scheduler import main as email_main
    await email_main()


if __name__ == '__main__':
    # Check for required environment variables
    if not os.getenv('TELEGRAM_BOT_TOKEN'):
        print("❌ Telegram bot token not found in TELEGRAM_BOT_TOKEN env var")
        sys.exit(1)

    asyncio.run(start_all())