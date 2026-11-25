"""Deliver one workflow email from the existing worker to its configured SMTP relay."""
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate
import os
from pathlib import Path
import smtplib
import ssl

from .account_email import normalize_email


DEFAULT_PORTS = {'starttls': 587, 'ssl': 465, 'plain': 25, 'local': 25}


def smtp_enabled():
    return all(os.environ.get('PLAN_REVIEW_SMTP_' + key, '').strip() for key in ('HOST', 'FROM'))


def _connection_settings():
    host = os.environ.get('PLAN_REVIEW_SMTP_HOST', '').strip()
    sender = normalize_email(os.environ.get('PLAN_REVIEW_SMTP_FROM'))
    mode = os.environ.get('PLAN_REVIEW_SMTP_MODE', 'starttls').strip().lower()
    if not host or not sender or mode not in DEFAULT_PORTS:
        raise ValueError('Incomplete SMTP configuration')
    port = int(os.environ.get('PLAN_REVIEW_SMTP_PORT') or DEFAULT_PORTS[mode])
    if not 1 <= port <= 65535:
        raise ValueError('Invalid SMTP port')
    if mode == 'local' and host not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Local SMTP mode requires a loopback relay')
    user = os.environ.get('PLAN_REVIEW_SMTP_USER', '')
    password = None
    if user:
        if mode not in ('starttls', 'ssl'):
            raise ValueError('SMTP credentials require TLS')
        secret_file = os.environ.get('PLAN_REVIEW_SMTP_PASSWORD_FILE')
        password = (Path(secret_file).read_text(encoding='utf-8-sig').rstrip('\r\n') if secret_file
                    else os.environ.get('PLAN_REVIEW_SMTP_PASSWORD'))
        if not password:
            raise ValueError('Missing SMTP password')
    return host, port, mode, sender, user, password


def _failure(error, *, after_checkpoint):
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return 'retry', 'SMTP_AUTH'
    if isinstance(error, smtplib.SMTPResponseException):
        if 400 <= error.smtp_code < 500:
            return 'retry', 'SMTP_TEMPORARY'
        if 500 <= error.smtp_code < 600:
            return 'failed', 'SMTP_REJECTED'
    if after_checkpoint:
        return 'failed', 'SMTP_UNCERTAIN'
    return 'retry', 'SMTP_TEMPORARY'


def send_workflow_mail(item, before_data):
    """Call before_data() once after RCPT. Only a confirmed DB checkpoint permits DATA."""
    try:
        host, port, mode, sender, user, password = _connection_settings()
    except (OSError, ValueError):
        return 'retry', 'SMTP_CONFIG'
    recipient = normalize_email(item['to'])
    if not recipient:
        raise ValueError('Missing workflow mail recipient')

    message = EmailMessage(policy=policy.SMTP)
    message['From'] = Address(display_name=item['sender_name'], addr_spec=sender)
    message['To'] = Address(addr_spec=recipient)
    message['Subject'] = item['subject']
    message['Message-ID'] = item['message_id']
    message['Date'] = formatdate(localtime=False, usegmt=True)
    message.set_content(item['text'], charset='utf-8', cte='quoted-printable')
    wire = message.as_bytes()

    smtp = None
    try:
        try:
            if mode == 'ssl':
                smtp = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
            else:
                smtp = smtplib.SMTP(host, port, timeout=20)
            smtp.ehlo_or_helo_if_needed()
            if mode == 'starttls':
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if user:
                smtp.login(user, password)
            for method, address in ((smtp.mail, sender), (smtp.rcpt, recipient)):
                code, reply = method(address)
                if not 200 <= code < 300:
                    raise smtplib.SMTPResponseException(code, reply)
        except (OSError, smtplib.SMTPException) as error:
            return _failure(error, after_checkpoint=False)

        # Allow checkpoint exceptions to propagate to the worker. No body has been sent.
        if not before_data():
            return 'retry', 'DELIVERY_SUPERSEDED'
        try:
            code, reply = smtp.data(wire)
            if not 200 <= code < 300:
                raise smtplib.SMTPResponseException(code, reply)
            return 'sent', None
        except (OSError, smtplib.SMTPException) as error:
            return _failure(error, after_checkpoint=True)
    finally:
        if smtp is not None:
            smtp.close()
