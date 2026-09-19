# -*- coding: utf-8 -*-
"""Lembretes de sessão.

No site: o painel mostra as sessões dos próximos dias em que você ainda não
respondeu, com os botões "vou / talvez / não posso" ali mesmo. Funciona sem
e-mail nenhum — no plano gratuito do PythonAnywhere é o jeito.

Por e-mail (só se MAIL_SERVER estiver configurado): `flask manutencao` manda,
uma vez por sessão, um lembrete a quem ainda não respondeu, com links que
confirmam a presença sem precisar entrar no site.
"""
from datetime import date, datetime, timedelta

from flask import current_app, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app import mail
from app.extensions import db
from app.models import Campaign, CampaignMember, GameSession, SessionAttendance, User

DAYS_AHEAD = 7        # o painel avisa de sessões até uma semana antes
EMAIL_DAYS_AHEAD = 2  # o e-mail sai dois dias antes
LINK_MAX_AGE = 10 * 24 * 3600
SALT = "presenca-sessao"


def pending_for(user, today=None):
    """[(sessão, campanha)] dos próximos dias que esta pessoa ainda não respondeu."""
    today = today or date.today()
    ids = [m.campaign_id for m in user.memberships.all()]
    if not ids:
        return []
    sessions = (GameSession.query.filter(
        GameSession.campaign_id.in_(ids), GameSession.status == "planejada",
        GameSession.scheduled_for.between(today, today + timedelta(days=DAYS_AHEAD)))
        .order_by(GameSession.scheduled_for).all())
    out = []
    for item in sessions:
        campaign = db.session.get(Campaign, item.campaign_id)
        if campaign.master_id == user.id:
            continue  # o mestre vê as respostas na própria sessão
        if item.attendance_of(user) is None:
            out.append((item, campaign))
    return out


def when_label(item, today=None):
    today = today or date.today()
    days = (item.scheduled_for - today).days
    text = {0: "hoje", 1: "amanhã"}.get(days, "em %d dias" % days)
    return text + (" às %s" % item.start_time if item.start_time else "")


# ------------------------------------------------------- links de presença
def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=SALT)


def attendance_token(item, user):
    return _serializer().dumps({"s": item.id, "u": user.id})


def from_token(token):
    try:
        data = _serializer().loads(token, max_age=LINK_MAX_AGE)
    except BadSignature:
        return None, None
    item = db.session.get(GameSession, data.get("s")) if isinstance(data, dict) else None
    user = db.session.get(User, data.get("u")) if isinstance(data, dict) else None
    if item is None or user is None:
        return None, None
    if CampaignMember.query.filter_by(campaign_id=item.campaign_id, user_id=user.id).first() is None:
        return None, None
    return item, user


def answer(item, user, status):
    record = item.attendance_of(user)
    if record is None:
        record = SessionAttendance(session_id=item.id, user_id=user.id)
        db.session.add(record)
    record.status = status
    return record


# ----------------------------------------------------------------- e-mail
EMAIL = """Olá, %(user)s!

A sessão %(number)d de %(campaign)s — "%(title)s" — é %(when)s.

Você vai?
  Vou:        %(yes)s
  Talvez:     %(maybe)s
  Não posso:  %(no)s

(Os links valem 10 dias. Você também pode responder no próprio site.)
"""


def send_due(today=None):
    """Manda os lembretes por e-mail que estão na hora. Devolve quantos saíram.

    Sem e-mail configurado não faz nada — o aviso no painel já cobre.
    """
    if not mail.enabled():
        return 0
    today = today or date.today()
    base = current_app.config.get("SITE_URL") or ""
    if not base:
        current_app.logger.warning("Lembretes por e-mail precisam de SITE_URL para montar os links.")
        return 0
    sent = 0
    due = GameSession.query.filter(
        GameSession.status == "planejada", GameSession.reminded_at.is_(None),
        GameSession.scheduled_for.between(today, today + timedelta(days=EMAIL_DAYS_AHEAD))).all()
    for item in due:
        campaign = db.session.get(Campaign, item.campaign_id)
        for member in campaign.members.all():
            user = member.user
            if user is None or user.id == campaign.master_id or item.attendance_of(user) is not None:
                continue
            token = attendance_token(item, user)
            link = lambda status: "%s%s?resposta=%s" % (base, url_for("campaigns.attendance_link", token=token), status)
            if mail.send(user.email, "Sessão %s: você vai?" % when_label(item, today), EMAIL % {
                    "user": user.username, "number": item.number, "campaign": campaign.name,
                    "title": item.title, "when": when_label(item, today),
                    "yes": link("vou"), "maybe": link("talvez"), "no": link("nao")}):
                sent += 1
        item.reminded_at = datetime.utcnow()
    db.session.commit()
    return sent
