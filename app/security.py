# -*- coding: utf-8 -*-
"""Freio contra tentativa e erro: senhas no login e códigos de convite.

As tentativas ficam no banco, não na memória do processo: no PythonAnywhere
cada Reload zeraria um contador em memória, e com mais de um processo web cada
um teria o seu.

Regras (janela de 15 minutos):
- 5 senhas erradas para o mesmo usuário bloqueiam esse usuário;
- 20 falhas vindas do mesmo IP bloqueiam o IP (pega quem testa várias contas);
- 20 códigos de convite inválidos do mesmo IP bloqueiam o IP. Um código tem
  ~16 milhões de combinações; nesse ritmo, adivinhar levaria séculos.
"""
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import current_app, request

from app.extensions import db

WINDOW = timedelta(minutes=15)
MAX_PER_ACCOUNT = 5
MAX_PER_IP = 20
KEEP = timedelta(days=2)


def client_ip():
    """IP de quem fez a requisição. Atrás de proxy (PythonAnywhere), o ProxyFix
    configurado em create_app já trocou remote_addr pelo IP real."""
    return (request.remote_addr or "?")[:64]


def _retry_after(query):
    from app.models import LoginAttempt
    since = datetime.utcnow() - WINDOW
    failures = query.filter(LoginAttempt.success.is_(False), LoginAttempt.created_at >= since)
    return failures


def seconds_blocked(identifier, ip, max_account=MAX_PER_ACCOUNT, max_ip=MAX_PER_IP):
    """Quanto falta para liberar (0 = liberado)."""
    from app.models import LoginAttempt
    now = datetime.utcnow()
    waits = [0]
    for column, value, limit in ((LoginAttempt.identifier, identifier, max_account),
                                 (LoginAttempt.ip, ip, max_ip)):
        if value is None or limit is None:
            continue
        failures = (_retry_after(LoginAttempt.query.filter(column == value))
                    .order_by(LoginAttempt.created_at.desc())
                    .limit(limit).all())
        if len(failures) >= limit:
            # Libera quando a mais antiga das últimas `limit` falhas sair da janela.
            waits.append((failures[-1].created_at + WINDOW - now).total_seconds())
    return max(0, int(max(waits)))


def record_attempt(identifier, ip, success):
    from app.models import LoginAttempt
    db.session.add(LoginAttempt(identifier=identifier[:160], ip=ip, success=success))
    if success:
        # Entrou: as falhas anteriores dessa conta deixam de contar.
        LoginAttempt.query.filter_by(identifier=identifier, success=False).delete()
    LoginAttempt.query.filter(LoginAttempt.created_at < datetime.utcnow() - KEEP).delete()
    db.session.commit()


def wait_message(seconds):
    minutes = max(1, (seconds + 59) // 60)
    return ("Muitas tentativas seguidas. Por segurança, espere %d minuto%s e tente de novo."
            % (minutes, "" if minutes == 1 else "s"))


def safe_next(value, fallback):
    """Só aceita destinos dentro do próprio site.

    "/painel" passa; "//site-malicioso.com", "https://..." e "/\\\\evil" não —
    senão um link de convite forjado poderia mandar a pessoa, já logada, para
    fora daqui.
    """
    if not value or not value.startswith("/") or value.startswith("//") or "\\" in value:
        return fallback
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return fallback
    return value


def behind_proxy(app):
    """No PythonAnywhere o app roda atrás de um proxy: sem isto todo mundo teria o
    mesmo IP (o do proxy), e o bloqueio por IP travaria todos de uma vez."""
    return bool(app.config.get("BEHIND_PROXY"))


def log_block(kind, identifier, ip):
    current_app.logger.warning("Bloqueio de %s: %s (ip %s)", kind, identifier, ip)
