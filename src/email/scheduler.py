"""Email scheduler - runs email monitoring on a regular interval."""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class EmailScheduler:
    """Schedules and runs email monitoring cycles."""

    def __init__(self, check_interval_minutes: int = 10):
        """
        Initialize email scheduler.

        Args:
            check_interval_minutes: How often to check emails (default: 10 min)
        """
        self.check_interval = check_interval_minutes * 60  # Convert to seconds
        self.task: Optional[asyncio.Task] = None
        self.running = False

        # Load email sources from config
        self.email_sources = self._load_email_sources()
        self.manager = self._create_manager()

    def _load_email_sources(self) -> dict[str, dict]:
        """Load email source configuration from environment or config."""
        sources = {}

        # Gmail
        gmail_email = os.getenv('GMAIL_EMAIL', 'ronnie@ronniebarnard.com')
        gmail_creds = os.getenv('GMAIL_CREDENTIALS_FILE')
        if gmail_email:
            sources['gmail'] = {
                'email': gmail_email,
                'credentials_file': gmail_creds or '.gmail_creds.json'
            }

        # Office 365 sources
        for suffix in ['fzzy', 'sopliance', 'infogility']:
            email_key = f'OFFICE365_EMAIL_{suffix.upper()}'
            tenant_key = f'OFFICE365_TENANT_{suffix.upper()}'
            client_id_key = f'OFFICE365_CLIENT_ID_{suffix.upper()}'
            client_secret_key = f'OFFICE365_CLIENT_SECRET_{suffix.upper()}'

            email_addr = os.getenv(email_key)
            tenant = os.getenv(tenant_key)
            client_id = os.getenv(client_id_key)
            client_secret = os.getenv(client_secret_key)

            if email_addr and tenant and client_id and client_secret:
                sources[f'office365_{suffix}'] = {
                    'email': email_addr,
                    'tenant_id': tenant,
                    'client_id': client_id,
                    'client_secret': client_secret
                }

        return sources

    def _create_manager(self):
        """Create email manager instance."""
        try:
            from .manager import EmailManager
            return EmailManager(self.email_sources)
        except Exception as e:
            logger.error(f"Failed to create EmailManager: {e}")
            raise

    async def check_email(self):
        """Perform a single email check cycle."""
        try:
            logger.info("\n" + "="*60)
            logger.info(f"📧 Email Monitor Check - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("="*60)

            # Run the manager's cycle
            counts = await self.manager.run_cycle()

            logger.info(f"📈 Summary:")
            for decision, count in counts.items():
                logger.info(f"   {decision.upper()}: {count}")

        except Exception as e:
            logger.error(f"Error during email check: {e}", exc_info=True)

            # Send error notification via Telegram
            await self._send_error_notification(str(e))

    async def _send_error_notification(self, error: str):
        """Send error notification via Telegram."""
        try:
            from vex.telegram.bot import _shared

            telegram_client = _shared.get('telegram_bot')
            if telegram_client:
                await telegram_client.send_message(
                    f"⚠️ EMAIL MONITOR ERROR\n\n"
                    f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"Error: {error[:200]}"
                )
        except:
            pass

    def start(self):
        """Start the email scheduler."""
        if self.running:
            logger.warning("Email scheduler already running")
            return

        self.running = True

        logger.info(f"Starting email scheduler (check every {self.check_interval/60:.1f} minutes)")

        # Create async task for the main loop
        self.task = asyncio.create_task(self._run_loop())

    async def _run_loop(self):
        """Main scheduling loop."""
        try:
            # Run first check immediately
            await self.check_email()

            # Then wait for interval and repeat
            while self.running:
                await asyncio.sleep(self.check_interval)
                await self.check_email()

        except asyncio.CancelledError:
            logger.info("Email scheduler cancelled")
        except Exception as e:
            logger.error(f"Scheduling error: {e}", exc_info=True)

    async def stop(self):
        """Stop the email scheduler."""
        if not self.running:
            return

        self.running = False

        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

        logger.info("Email scheduler stopped")


# ──────────────────────────────────────────────────────────────────────
# Entry point functions
# ──────────────────────────────────────────────────────────────────────

async def main():
    """Main entry point for email scheduler."""
    # Set up logging
    log_level = os.getenv('EMAIL_LOG_LEVEL', 'INFO')
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    scheduler = EmailScheduler(check_interval_minutes=10)
    scheduler.start()

    # Keep running until interrupted
    try:
        # Set signal handlers for graceful shutdown
        loop = asyncio.get_event_loop()
        for sig in [signal.SIGTERM, signal.SIGINT]:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(scheduler.stop()))

        # Wait until cancelled
        while scheduler.running:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        await scheduler.stop()
        print("\n🛑 Email scheduler stopped")


def run_scheduler():
    """Run the email scheduler as a standalone process."""
    asyncio.run(main())


if __name__ == '__main__':
    run_scheduler()