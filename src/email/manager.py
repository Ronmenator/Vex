"""Email management logic - processing, categorizing, and drafting."""

import json
import logging
import os
import re
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field

from .client import Email, EmailClient, GmailClient, Office365Client

logger = logging.getLogger(__name__)


@dataclass
class EmailDecision:
    """Decision made about an email."""
    email_id: str
    source: str
    decision: str  # 'spam', 'archive', 'interesting', 'routine'
    score: float = 0.0
    reason: str = ""
    reply_draft: str = ""


class EmailClassifier:
    """Classifies emails to determine how to handle them."""

    # Keywords that suggest spam
    SPAM_KEYWORDS = [
        'one time offer', 'claim now', 'winner', 'congratulations',
        'urgently need', 'verify your account', 'click here immediately',
        'no credit card required', 'exclusive deal', 'limited time only',
        'password reset', 'verify identity', 'your account suspended',
        'login attempt', 'account compromised', 'security alert',
        'instant cash', 'earn $', 'click and win', 'miracle cure',
        'free gift', 'no work needed', 'passive income', 'get rich quick'
    ]

    # Keywords that suggest interesting content
    INTERESTING_KEYWORDS = [
        # Productivity & Tools
        'launch', 'new version', 'update', 'feature', 'beta',
        'automate', 'plugin', 'extension', 'tool', 'framework',
        'integration', 'api', 'gpt', 'ai', 'machine learning',
        'workflow', 'automation', 'productivity hack', 'save time',

        # Business & Networking
        'partnership', 'collaboration', 'sponsor', 'conference',
        'event', 'webinar', 'demo', 'podcast', 'interview',

        # Sales & Offers
        'discount', 'offer', 'promotion', 'sale', 'deal',
        'early access', 'limited', 'presale', 'early bird',

        # Professional Development
        'certificate', 'course', 'workshop', 'training', 'learn',
        'newsletter', 'insight', 'trend', 'market'
    ]

    @classmethod
    def classify(cls, email: Email) -> EmailDecision:
        """Classify an email and decide how to handle it."""
        sender_email = email.sender_email.lower()
        domain = sender_email.split('@')[-1]

        # Check if known contacts (white list)
        if cls._is_known_contact(sender_email, domain):
            return cls._make_decision(email, 'interesting', score=0.9, reason='Known contact')

        # Check for spam indicators
        spam_score = 0
        reason = ""

        text_to_check = (email.subject + ' ' + email.preview + ' ' + email.body).lower()
        spam_found = []

        for keyword in cls.SPAM_KEYWORDS:
            if keyword.lower() in text_to_check:
                spam_score += 1
                spam_found.append(keyword)

        if spam_score >= 2:
            return cls._make_decision(email, 'spam', score=0.0,
                                      reason=f"Spam indicators: {', '.join(set(spam_found))}")

        # Check for interesting content
        interesting_score = 0
        interesting_found = []

        for keyword in cls.INTERESTING_KEYWORDS:
            if keyword.lower() in text_to_check:
                interesting_score += 1
                interesting_found.append(keyword)

        # Scoring thresholds
        if spam_score > 0:
            return cls._make_decision(email, 'archive', score=0.5,
                                      reason="Low confidence spam")

        if interesting_score >= 2:
            return cls._make_decision(email, 'interesting', score=0.8,
                                      reason="Promising content: " +
                                             ", ".join(set(interesting_found))[:100])

        if interesting_score == 1 and 'sale' in text_to_check.lower():
            return cls._make_decision(email, 'interesting', score=0.6,
                                      reason="Potential sale/promotion")

        # Check sender domain
        if domain in ['gmail.com', 'outlook.com', 'yahoo.com']:
            return cls._make_decision(email, 'interesting', score=0.4,
                                      reason="Personal email account")
        elif domain.endswith('.ai') or domain.endswith('.com'):
            return cls._make_decision(email, 'interesting', score=0.5,
                                      reason="Professional domain")
        elif domain.endswith('.io'):
            return cls._make_decision(email, 'interesting', score=0.7,
                                      reason="Startup domain")

        # Default: routine - no action needed
        return cls._make_decision(email, 'routine', score=0.2, reason="Not relevant")

    @classmethod
    def _is_known_contact(cls, email_addr: str, domain: str) -> bool:
        """Check if sender is in known contacts."""
        # Load from a potential contacts file if it exists
        contacts_file = os.getenv('EMAIL_CONTACTS_FILE', '.email_contacts.json')
        if not os.path.exists(contacts_file):
            return False

        try:
            with open(contacts_file) as f:
                contacts = json.load(f)

            return email_addr in contacts.get('emails', []) or domain in contacts.get('domains', [])
        except:
            return False

    @classmethod
    def _make_decision(cls, email: Email, decision: str, score: float, reason: str) -> EmailDecision:
        """Create email decision object."""
        return EmailDecision(
            email_id=email.id,
            source=email.source,
            decision=decision,
            score=score,
            reason=reason
        )


class EmailProcessor:
    """Processes emails through the classification and drafting pipeline."""

    def __init__(self, clients: dict[str, EmailClient]):
        self.clients = clients
        self.classifier = EmailClassifier()

    async def process_all(self) -> list[EmailDecision]:
        """Check all email sources and process new emails."""
        all_decisions = []

        for source, client in self.clients.items():
            logger.info(f"Checking {source} for new emails")

            # Get unread emails (no time filter on first run)
            emails = await client.get_unread_emails()

            for email in emails:
                decision = self.classifier.classify(email)
                all_decisions.append(decision)

                # Handle based on decision
                if decision.decision == 'spam':
                    await client.delete_email(email.id)
                    logger.info(f"✅ Deleted spam: {email.subject[:50]}")

                elif decision.decision == 'archive':
                    await client.delete_email(email.id)  # Archive instead of full delete
                    logger.info(f"📦 Archived: {email.subject[:50]}")

                elif decision.decision == 'interesting':
                    # Generate reply and save as draft
                    reply_text = self._generate_reply(email)
                    draft_id = client.draft_reply(email, reply_text)
                    logger.info(f"📝 Drafted reply for: {email.subject[:50]})")

                    if reply_text:
                        # Send notification for interesting emails
                        await self._send_interesting_notification(email, reply_text)

        return all_decisions

    def _generate_reply(self, email: Email) -> str:
        """Generate a reply to an interesting email."""
        # Load Ronnie's reply preferences/style
        reply_style = self._load_reply_style()

        subject = email.subject
        sender = email.sender
        preview = email.preview

        # Generate personalized reply
        reply = f"Hi {sender},\n\n"
        reply += f"I received your email about: "{subject}"\n\n"
        reply += f"Preview: {preview}\n\n"
        reply += "What specific action would you like from me? I can schedule a call, discuss a partnership, or help with the project mentioned.\n\n"
        reply += "Best regards,\nRonnie\n"
        reply += f"---\n"
        reply += f"Sent: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"

        return reply

    def _load_reply_style(self) -> dict:
        """Load Ronnie's reply preferences from a cache."""
        style_file = '.email_reply_style.json'
        if not os.path.exists(style_file):
            return {}

        try:
            with open(style_file) as f:
                return json.load(f)
        except:
            return {}

    async def _send_interesting_notification(self, email: Email, reply: str):
        """Send Telegram notification for interesting emails."""
        try:
            from vex.telegram.bot import _shared

            telegram_client = _shared.get('telegram_bot')
            if telegram_client:
                message = (
                    f"🎯 INTERESTING EMAIL\n\n"
                    f"📧 {email.sender_email}\n"
                    f"📝 {email.subject[:80]}\n"
                    f"⏰ {email.received_date.strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"Sent reply draft! Review and send as needed.\n\n"
                    f"📍 {email.source}"
                )
                await telegram_client.send_message(message)

        except Exception as e:
            logger.warning(f"Failed to send Telegram notification: {e}")

    def log_metrics(self, decisions: list[EmailDecision]):
        """Log processing metrics to file."""
        metrics = {
            'timestamp': datetime.now().isoformat(),
            'sources': list(self.clients.keys()),
            'decision_counts': {},
            'by_source': {}
        }

        for d in decisions:
            metrics['decision_counts'][d.decision] = metrics['decision_counts'].get(d.decision, 0) + 1

            source_counts = metrics['by_source'].setdefault(d.source, {})
            source_counts[d.decision] = source_counts.get(d.decision, 0) + 1

        # Save to /tmp directory
        metrics_file = '/tmp/email_metrics.txt'
        with open(metrics_file, 'a') as f:
            f.write(json.dumps(metrics) + '\n')

        logger.info(f"Metrics logged to {metrics_file}")


class EmailManager:
    """Main email management coordinator."""

    def __init__(self, sources: dict[str, dict]):
        self.clients = {}
        self.processor = None

        # Initialize clients for each source
        for source_key, source_config in sources.items():
            if source_key == 'gmail':
                self.clients[source_key] = GmailClient(source_config['email'])
            elif source_key.startswith('office365'):
                email = source_config['email']
                client = Office365Client(
                    email=email,
                    tenant_id=source_config['tenant_id'],
                    client_id=source_config['client_id'],
                    client_secret=source_config['client_secret']
                )
                self.clients[source_key] = client

    async def run_cycle(self) -> dict[str, int]:
        """Run a full email processing cycle."""
        logger.info("Starting email processing cycle")

        processor = EmailProcessor(self.clients)
        decisions = await processor.process_all()
        processor.log_metrics(decisions)

        # Count decisions by type
        counts = {d.decision: 0 for d in decisions}
        for d in decisions:
            counts[d.decision] += 1

        logger.info(f"Cycle complete: {counts}")
        return counts