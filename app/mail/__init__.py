"""Mail integration package.

Mail access is hidden behind the provider-agnostic :class:`MailProvider`
facade and the domain models in :mod:`app.mail.models`. Gmail/OAuth2 is the
only v1 implementation; callers never import provider-specific types.
"""

from app.mail.base import MailProvider
from app.mail.models import EmailMessage, OutgoingMessage, SyncResult

__all__ = ["MailProvider", "EmailMessage", "OutgoingMessage", "SyncResult"]
