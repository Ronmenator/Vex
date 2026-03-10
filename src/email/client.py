"""Email API client for Gmail and Office365."""

import os
import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Email:
    """Single email representation."""
    id: str
    source: str
    sender: str
    sender_email: str
    subject: str
    preview: str
    body: str
    received_date: datetime
    is_read: bool = False
    labels: list[str] = field(default_factory=list)
    has_attachments: bool = False


class EmailClient:
    """Base email client."""

    def get_unread_emails(self, since: Optional[datetime] = None) -> list[Email]:
        """Get unread emails from source."""
        raise NotImplementedError

    def get_email_by_id(self, email_id: str) -> Optional[Email]:
        """Get email by ID."""
        raise NotImplementedError

    def delete_email(self, email_id: str) -> bool:
        """Delete/SPAM an email."""
        raise NotImplementedError

    def draft_reply(self, email: Email, reply_text: str) -> str:
        """Save a reply draft. Returns draft ID."""
        raise NotImplementedError

    def get_drafts(self) -> list[Email]:
        """Get available drafts."""
        raise NotImplementedError

    def delete_draft(self, draft_id: str) -> bool:
        """Delete a draft."""
        raise NotImplementedError


class GmailClient(EmailClient):
    """Google Gmail API client."""

    def __init__(self, email: str):
        self.email = email
        self._api: Optional[Any] = None
        self._service: Optional[Any] = None

    async def _ensure_service(self):
        """Initialize Gmail service."""
        if self._service:
            return

        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            # Check for credentials file
            creds_file = os.getenv("GMAIL_CREDENTIALS_FILE", "~/.gmail_creds.json")
            if not os.path.exists(os.path.expanduser(creds_file)):
                raise FileNotFoundError(
                    f"Gmail credentials not found. Create OAuth token at {creds_file}.\n"
                    "Visit https://console.cloud.google.com/apis/credentials and export a "
                    "Chrome browser session as a token file."
                )

            # Load credentials
            creds_data = json.load(open(os.path.expanduser(creds_file)))
            creds = Credentials(token=creds_data['token'])

            # Build Gmail service
            self._service = build('gmail', 'v1', credentials=creds)
            logger.info(f"Gmail service initialized for {self.email}")

        except Exception as e:
            logger.error(f"Failed to initialize Gmail: {e}")
            raise

    async def get_unread_emails(self, since: Optional[datetime] = None) -> list[Email]:
        """Get unread emails from Gmail."""
        await self._ensure_service()

        query = "is:unread"
        if since:
            query += f" after:{since.strftime('%Y/%m/%d')}"

        try:
            results = self._service.users().messages().list(
                userId='me', q=query, maxResults=500
            ).execute()

            messages = results.get('messages', [])
            emails = []

            for msg in messages:
                email_data = self.get_email_by_id(msg['id'])
                if email_data:
                    emails.append(email_data)

            logger.info(f"Found {len(emails)} unread emails from Gmail")
            return emails

        except Exception as e:
            logger.error(f"Gmail lookup error: {e}")
            return []

    def get_email_by_id(self, email_id: str) -> Optional[Email]:
        """Get email by ID."""
        try:
            msg = self._service.users().messages().get(
                userId='me', id=email_id, format='full'
            ).execute()

            headers = {h['name'].lower(): h['value'] for h in msg['payload']['headers']}

            subject = headers.get('subject', 'No Subject')
            sender = headers.get('from', 'Unknown')
            sender_email = self._parse_email_address(sender)
            received = datetime.fromtimestamp(int(msg['internalDate']) / 1000)

            # Extract body
            body = self._get_email_body(msg)
            preview = body[:200] if body else ''

            email = Email(
                id=email_id,
                source='gmail',
                sender=sender,
                sender_email=sender_email,
                subject=subject,
                preview=preview,
                body=body,
                received_date=received,
                is_read=not any(l.lower() == 'unread' for l in msg.get('labelIds', []))
            )
            return email

        except Exception as e:
            logger.error(f"Failed to get email {email_id}: {e}")
            return None

    async def delete_email(self, email_id: str) -> bool:
        """Archive/SPAM an email."""
        try:
            # Try SPAM first, if not present use ARCHIVE
            self._service.users().messages().trash(
                userId='me', id=email_id
            ).execute()
            logger.info(f"Moved {email_id} to trash")
            return True
        except Exception as e:
            logging.error(f"Failed to delete {email_id}: {e}")
            return False

    def draft_reply(self, email: Email, reply_text: str) -> str:
        """Create a reply draft in Gmail."""
        try:
            message = _create_gmail_message(
                to=email.sender_email,
                subject=f"Re: {email.subject}",
                body=reply_text
            )

            draft = self._service.users().drafts().create(
                userId='me', body={'message': message}
            ).execute()

            draft_id = draft['id']
            logger.info(f"Draft {draft_id} created for email {email.id}")
            return draft_id

        except Exception as e:
            logger.error(f"Failed to create draft: {e}")
            return ""

    def get_drafts(self) -> list[Email]:
        """Get existing drafts."""
        try:
            results = self._service.users().drafts().list(
                userId='me', maxResults=100
            ).execute()

            drafts = results.get('drafts', [])
            emails = []

            for draft in drafts:
                draft_id = draft['id']
                draft_data = self._service.users().drafts().get(
                    userId='me', id=draft_id, format='full'
                ).execute()

                msg = draft_data['message']
                headers = {h['name'].lower(): h['value'] for h in msg['payload']['headers']}
                subject = headers.get('subject', 'No Subject')
                received = datetime.fromtimestamp(int(msg['internalDate']) / 1000)

                body = self._get_email_body(msg)

                emails.append(Email(
                    id=f"DRAFT_{draft_id}",
                    source='gmail',
                    sender='You',
                    sender_email=self.email,
                    subject=subject,
                    preview=body[:200] if body else '',
                    body=body,
                    received_date=received,
                    is_read=True
                ))

            return emails

        except Exception as e:
            logger.error(f"Failed to get drafts: {e}")
            return []

    def delete_draft(self, draft_id: str) -> bool:
        """Delete a draft."""
        try:
            self._service.users().drafts().delete(userId='me', id=draft_id).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to delete draft {draft_id}: {e}")
            return False

    def _get_email_body(self, msg: dict) -> str:
        """Extract plain body from Gmail message."""
        if 'parts' in msg['payload']:
            return self._get_parts_text(msg['payload']['parts'])
        elif 'body' in msg['payload'] and 'data' in msg['payload']['body']:
            return _decode_base64(msg['payload']['body']['data'])
        return ''

    def _get_parts_text(self, parts: list) -> str:
        """Recursively extract text from message parts."""
        text_parts = []

        for part in parts:
            if 'body' in part and 'data' in part['body']:
                try:
                    text = _decode_base64(part['body']['data'])
                    text_parts.append(text)
                except:
                    continue

            if 'parts' in part:
                text_parts.append(self._get_parts_text(part['parts']))

        return '\n'.join(text_parts)

    @staticmethod
    def _parse_email_address(address: str) -> str:
        """Extract email from address string."""
        from email.utils import parseaddr
        return parseaddr(address)[1] or address


class Office365Client(EmailClient):
    """Microsoft Graph API client for Office365."""

    def __init__(self, email: str, tenant_id: str, client_id: str, client_secret: str):
        self.email = email
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._graph: Optional[Any] = None

    async def _ensure_graph(self):
        """Initialize Graph service."""
        if self._graph:
            return

        try:
            from msal import ConfidentialClientApplication
            from graphy import GraphClient

            scope = ["https://graph.microsoft.com/.default"]

            app = ConfidentialClientApplication(
                self.client_id,
                authority=f"https://login.microsoftonline.com/{self.tenant_id}",
                client_credential=self.client_secret,
            )

            result = app.acquire_token_for_client(scopes=scope)
            if 'access_token' in result:
                self._graph = GraphClient(token=result['access_token'])
                logger.info(f"Graph client initialized for {self.email}")
            else:
                raise Exception(f"Failed to acquire token: {result.get('error_description')}")

        except Exception as e:
            logger.error(f"Failed to initialize Graph: {e}")
            raise

    async def get_unread_emails(self, since: Optional[datetime] = None) -> list[Email]:
        """Get unread emails from Office365."""
        await self._ensure_graph()

        query = "?$filter=isRead eq false"
        if since:
            from datetime import timedelta
            since_date = since - timedelta(minutes=10)
            query += f"&$filter/receivedDateTime ge {since_date.isoformat()}Z"

        try:
            emails = []
            response = await self._graph.mail.get(query)

            for msg in response['value']:
                email = Email(
                    id=msg['id'],
                    source='office365',
                    sender=msg['from']['emailAddress']['name'],
                    sender_email=msg['from']['emailAddress']['address'],
                    subject=msg['subject'],
                    preview=msg['bodyPreview'],
                    body=msg['body'],
                    received_date=datetime.fromisoformat(msg['receivedDateTime'].replace('Z', '+00:00')),
                    is_read=msg.get('isRead', False)
                )
                emails.append(email)

            logger.info(f"Found {len(emails)} unread emails from {self.email}")
            return emails

        except Exception as e:
            logger.error(f"Office365 lookup error: {e}")
            return []

    def get_email_by_id(self, email_id: str) -> Optional[Email]:
        """Get email by ID."""
        try:
            msg = self._graph.mail.get(email_id)

            return Email(
                id=msg['id'],
                source='office365',
                sender=msg['from']['emailAddress']['name'],
                sender_email=msg['from']['emailAddress']['address'],
                subject=msg['subject'],
                preview=msg['bodyPreview'],
                body=msg['body'],
                received_date=datetime.fromisoformat(msg['receivedDateTime'].replace('Z', '+00:00')),
                is_read=msg.get('isRead', False)
            )

        except Exception as e:
            logger.error(f"Failed to get email {email_id}: {e}")
            return None

    async def delete_email(self, email_id: str) -> bool:
        """Soft delete (move to archive) an email."""
        try:
            self._graph.mail.trash(email_id)
            return True
        except Exception as e:
            logger.error(f"Failed to delete {email_id}: {e}")
            return False

    def draft_reply(self, email: Email, reply_text: str) -> str:
        """Create a reply draft in Office365."""
        try:
            draft_id = await self._graph.mail.create_draft(
                to=email.sender_email,
                subject=f"Re: {email.subject}",
                body=reply_text
            )
            logger.info(f"Draft {draft_id} created for email {email.id}")
            return draft_id

        except Exception as e:
            logger.error(f"Failed to create draft: {e}")
            return ""

    def get_drafts(self) -> list[Email]:
        """Get existing drafts."""
        try:
            drafts = await self._graph.mail.get_my_drafts()
            emails = []

            for draft in drafts['value']:
                emails.append(Email(
                    id=f"DRAFT_{draft['id']}",
                    source='office365',
                    sender='You',
                    sender_email=self.email,
                    subject=draft['subject'],
                    preview=draft['bodyPreview'],
                    body=draft['body'],
                    received_date=datetime.fromisoformat(draft['createdDateTime'].replace('Z', '+00:00')),
                    is_read=True
                ))

            return emails

        except Exception as e:
            logger.error(f"Failed to get drafts: {e}")
            return []

    def delete_draft(self, draft_id: str) -> bool:
        """Delete a draft."""
        try:
            self._graph.mail.delete_draft(draft_id)
            return True
        except Exception as e:
            logger.error(f"Failed to delete draft {draft_id}: {e}")
            return False


# ───── Utility functions ─────

def _decode_base64(data: str) -> str:
    """Decode Gmail base64url encoded data."""
    import re
    data = re.sub(r'_', '/', data)
    data = re.sub(r'-', '+', data)
    padding = len(data) % 4
    if padding:
        data += '=' * (4 - padding)
    return base64.b64decode(data).decode('utf-8', errors='ignore')


def _create_gmail_message(to: str, subject: str, body: str) -> dict:
    """Create Gmail API message dict."""
    import re

    message = f"From: {to}\n"
    message += f"To: {to}\n"
    message += f"Subject: {subject}\n\n"
    message += body

    encoded = base64.urlsafe_b64encode(message.encode('utf-8')).decode('utf-8')
    return {'raw': encoded}