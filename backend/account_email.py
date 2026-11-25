"""Single SMTP recipient addresses shared by account maintenance and delivery."""
import re


EMAIL_ERROR = '请填写一个有效的通知邮箱'
LOCAL_ATOM = r"[A-Za-z0-9!#$%&'*+/=?^`_{}|~-]+"
LOCAL_PART = re.compile(rf'{LOCAL_ATOM}(?:\.{LOCAL_ATOM})*')
DOMAIN_LABEL = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?')


def normalize_email(value):
    """Accept an optional, bare mailbox for a single recipient."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.isascii():
        raise ValueError(EMAIL_ERROR)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(EMAIL_ERROR)
    address = value.strip(' ')
    if not address:
        return None
    local, at, domain = address.partition('@')
    labels = domain.split('.')
    if (len(address) > 254 or not at or len(local) > 64 or not LOCAL_PART.fullmatch(local)
            or len(labels) < 2 or any(not DOMAIN_LABEL.fullmatch(label) for label in labels)):
        raise ValueError(EMAIL_ERROR)
    return f'{local}@{domain.lower()}'


def notification_email(user):
    """Prefer the configured mailbox, falling back to an actual email login."""
    for candidate in (user.email, user.username):
        try:
            address = normalize_email(candidate)
        except ValueError:
            continue
        if address:
            return address
    return None
