"""Email automation module for Vex."""

__all__ = [
    'EmailClient',
    'GmailClient',
    'Office365Client',
    'Email',
    'EmailClassifier',
    'EmailProcessor',
    'EmailManager',
    'EmailScheduler',
    'main', 'run_scheduler'
]

from .client import Email, EmailClient, GmailClient, Office365Client
from .manager import EmailClassifier, EmailProcessor, EmailManager
from .scheduler import EmailScheduler, main, run_scheduler

__version__ = '0.1.0'