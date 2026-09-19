# -*- coding: utf-8 -*-
"""Envio de e-mail (só o de recuperar senha, por enquanto).

Configuração por variáveis de ambiente (ver config.py):
    MAIL_SERVER    ex.: smtp.gmail.com
    MAIL_PORT      587 (STARTTLS) ou 465 (SSL)
    MAIL_USERNAME  a conta que envia
    MAIL_PASSWORD  no Gmail, uma "senha de app", não a senha da conta
    MAIL_FROM      remetente mostrado (padrão: MAIL_USERNAME)

Sem MAIL_SERVER o envio fica desligado e a tela de recuperação explica isso.
Nos testes (TESTING) nada sai: as mensagens vão para app.extensions["outbox"].
"""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from flask import current_app

TIMEOUT = 15


def enabled():
    config = current_app.config
    return bool(current_app.testing or config.get("MAIL_SERVER"))


def send(to, subject, body):
    """Envia texto puro. Devolve True se saiu (ou foi para a caixa de teste)."""
    app = current_app
    if app.testing:
        app.extensions.setdefault("outbox", []).append({"to": to, "subject": subject, "body": body})
        return True
    config = app.config
    if not config.get("MAIL_SERVER"):
        return False

    message = EmailMessage()
    sender = config.get("MAIL_FROM") or config.get("MAIL_USERNAME")
    message["From"] = formataddr(("Grimório", sender))
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    port = int(config.get("MAIL_PORT") or 587)
    context = ssl.create_default_context()
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(config["MAIL_SERVER"], port, timeout=TIMEOUT, context=context)
        else:
            server = smtplib.SMTP(config["MAIL_SERVER"], port, timeout=TIMEOUT)
            server.starttls(context=context)
        with server:
            if config.get("MAIL_USERNAME"):
                server.login(config["MAIL_USERNAME"], config.get("MAIL_PASSWORD") or "")
            server.send_message(message)
        return True
    except (OSError, smtplib.SMTPException) as error:
        app.logger.error("Falha ao enviar e-mail para %s: %s", to, error)
        return False
