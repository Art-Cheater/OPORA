"""Кто видит входящие письма: ящик целиком или только пересланные."""

from __future__ import annotations

from app.models.auth.constants import PERM_INQUIRIES_DELETE, PERM_INQUIRIES_SYNC
from app.models.inquiries.inquiry import Inquiry


def manages_mailbox(user) -> bool:
    """Диспетчер / директор / админ: видят все письма ящика."""
    if user is None:
        return False
    return bool(user.is_admin or user.has_any_permission(PERM_INQUIRIES_SYNC, PERM_INQUIRIES_DELETE))


def can_access_inquiry(user, inquiry: Inquiry) -> bool:
    if user is None or inquiry is None:
        return False
    if manages_mailbox(user):
        return True
    return inquiry.assigned_to is not None and inquiry.assigned_to == user.id
