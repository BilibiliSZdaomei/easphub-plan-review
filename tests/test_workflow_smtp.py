import socket
import socketserver
import threading
from email import policy
from email.parser import BytesParser
from unittest.mock import Mock

import pytest

from backend.workflow_smtp import send_workflow_mail, smtp_enabled


MAIL = {
    'id': 'test-mail-01', 'message_id': '<test-mail-01@mail.example.invalid>',
    'sender_name': 'EASPhub 计划审核', 'to': 'reviewer@example.invalid',
    'subject': 'QA-01 · 待领取复审 / Ready for review',
    'text': '计划已提交。请领取复审。\nReview the plan.\n.开头带点的行',
}


class SMTPReceiver(socketserver.StreamRequestHandler):
    def reply(self, text):
        self.wfile.write(text.encode('ascii') + b'\r\n')

    def handle(self):
        smtp = self.server
        smtp.connections += 1
        self.reply('220 fixture ready')
        for command in self.rfile:
            verb, _, value = command.decode('ascii').strip().partition(' ')
            smtp.events.append(verb.upper())
            if verb.upper() in ('EHLO', 'HELO'):
                self.reply('250 fixture')
            elif verb.upper() == 'MAIL':
                smtp.senders.append(value.removeprefix('FROM:').removeprefix('from:'))
                self.reply('250 OK')
            elif verb.upper() == 'RCPT':
                smtp.recipients.append(value.removeprefix('TO:').removeprefix('to:'))
                self.reply(f'{smtp.rcpt_code} recipient')
            elif verb.upper() == 'DATA':
                self.reply('354 end with period')
                lines = []
                for line in self.rfile:
                    if line == b'.\r\n':
                        break
                    lines.append(line[1:] if line.startswith(b'..') else line)
                smtp.messages.append(b''.join(lines))
                if smtp.data_code is None:  # Lose the connection before SMTP's final reply.
                    return
                self.reply(f'{smtp.data_code} result')
            else:
                self.reply('500 unsupported')


@pytest.fixture
def smtp(monkeypatch):
    for name in ('PLAN_REVIEW_SMTP_USER', 'PLAN_REVIEW_SMTP_PASSWORD', 'PLAN_REVIEW_SMTP_PASSWORD_FILE'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PLAN_REVIEW_SMTP_MODE', 'local')
    monkeypatch.setenv('PLAN_REVIEW_SMTP_HOST', '127.0.0.1')
    monkeypatch.setenv('PLAN_REVIEW_SMTP_FROM', 'no-reply@example.invalid')
    monkeypatch.setattr(socket, 'getfqdn', lambda *args: 'localhost')
    with socketserver.ThreadingTCPServer(('127.0.0.1', 0), SMTPReceiver) as server:
        server.connections = 0
        server.senders, server.recipients, server.messages, server.events = [], [], [], []
        server.rcpt_code, server.data_code = 250, 250
        monkeypatch.setenv('PLAN_REVIEW_SMTP_PORT', str(server.server_address[1]))
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_mime_and_envelope_reach_relay_only_after_db_checkpoint(smtp):
    def before_data():
        smtp.events.append('DB_CHECKPOINT')
        return True

    assert smtp_enabled()
    assert send_workflow_mail(MAIL, before_data) == ('sent', None)
    assert smtp.events == ['EHLO', 'MAIL', 'RCPT', 'DB_CHECKPOINT', 'DATA']
    assert smtp.senders == ['<no-reply@example.invalid>']
    assert smtp.recipients == ['<reviewer@example.invalid>']
    raw, = smtp.messages
    message = BytesParser(policy=policy.default).parsebytes(raw)
    assert message['From'].addresses[0].display_name == MAIL['sender_name']
    assert message['From'].addresses[0].addr_spec == 'no-reply@example.invalid'
    assert message['To'].addresses[0].addr_spec == MAIL['to']
    assert message['Subject'] == MAIL['subject']
    assert message['Message-ID'] == MAIL['message_id']
    assert message.get_content_type() == 'text/plain'
    assert message.get_content_charset() == 'utf-8'
    assert message.get_content().splitlines() == MAIL['text'].splitlines()


@pytest.mark.parametrize('phase', ['rcpt_code', 'data_code'])
@pytest.mark.parametrize('reply,result', [
    (450, ('retry', 'SMTP_TEMPORARY')),
    (550, ('failed', 'SMTP_REJECTED')),
])
def test_explicit_relay_responses(smtp, phase, reply, result):
    setattr(smtp, phase, reply)
    checkpoints = []
    def before_data():
        checkpoints.append(True)
        return True
    assert send_workflow_mail(MAIL, before_data) == result
    assert bool(checkpoints) == (phase == 'data_code')
    assert bool(smtp.messages) == (phase == 'data_code')


@pytest.mark.parametrize('response', [None, 350])
def test_missing_or_invalid_final_response_is_uncertain(smtp, response):
    smtp.data_code = response
    assert send_workflow_mail(MAIL, lambda: True) == ('failed', 'SMTP_UNCERTAIN')
    assert len(smtp.messages) == smtp.connections == 1


def test_revoked_lease_or_failed_checkpoint_never_writes_data(smtp):
    assert send_workflow_mail(MAIL, lambda: False) == ('retry', 'DELIVERY_SUPERSEDED')
    def db_failed():
        raise OSError('fixture checkpoint failed')
    with pytest.raises(OSError, match='fixture checkpoint'):
        send_workflow_mail(MAIL, db_failed)
    assert not smtp.messages
    assert 'DATA' not in smtp.events


@pytest.mark.parametrize('name', ['HOST', 'FROM'])
def test_unconfigured_smtp_is_disabled(smtp, monkeypatch, name):
    monkeypatch.delenv('PLAN_REVIEW_SMTP_'+name)
    assert not smtp_enabled()
    assert send_workflow_mail(MAIL, lambda: pytest.fail('unexpected checkpoint')) == ('retry', 'SMTP_CONFIG')
    assert smtp.connections == 0


def test_explicit_plain_relay_accepts_mail_but_never_transmits_login(smtp, monkeypatch):
    monkeypatch.setenv('PLAN_REVIEW_SMTP_MODE', 'plain')
    assert send_workflow_mail(MAIL, lambda: True) == ('sent', None)
    monkeypatch.setenv('PLAN_REVIEW_SMTP_USER', 'fixture-user')
    assert send_workflow_mail(MAIL, lambda: pytest.fail('unexpected checkpoint')) == ('retry', 'SMTP_CONFIG')
    assert smtp.connections == 1
    assert 'AUTH' not in smtp.events


@pytest.mark.parametrize('mode,port', [('starttls',587), ('ssl',465)])
def test_empty_port_defaults_and_authenticated_tls_from_secret_file(smtp, monkeypatch, tmp_path, mode, port):
    from backend import workflow_smtp

    password_file = tmp_path / 'fixture-password'
    password_file.write_text('synthetic password\n', encoding='utf-8')
    monkeypatch.setenv('PLAN_REVIEW_SMTP_MODE', mode)
    monkeypatch.setenv('PLAN_REVIEW_SMTP_PORT', '')
    monkeypatch.setenv('PLAN_REVIEW_SMTP_USER', 'fixture-user')
    monkeypatch.setenv('PLAN_REVIEW_SMTP_PASSWORD_FILE', str(password_file))
    relay = Mock()
    relay.mail.return_value = relay.rcpt.return_value = relay.data.return_value = (250, b'ok')
    factory = Mock(return_value=relay)
    monkeypatch.setattr(workflow_smtp.smtplib, 'SMTP' if mode == 'starttls' else 'SMTP_SSL', factory)
    assert send_workflow_mail(MAIL, lambda: True) == ('sent', None)
    assert factory.call_args.args == ('127.0.0.1',port)
    if mode == 'starttls':
        assert [call[0] for call in relay.method_calls][:4] == ['ehlo_or_helo_if_needed', 'starttls', 'ehlo', 'login']
    else:
        assert 'context' in factory.call_args.kwargs
        relay.starttls.assert_not_called()
    relay.login.assert_called_once_with('fixture-user','synthetic password')
