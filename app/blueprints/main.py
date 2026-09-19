# -*- coding: utf-8 -*-
from datetime import date

from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user, login_required

from app.models import SessionAttendance, Campaign, Character, GameSession, GameSystem

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    systems = GameSystem.query.filter_by(is_preset=True).all()
    return render_template("main/landing.html", systems=systems)


@bp.route("/painel")
@login_required
def dashboard():
    mastering = (
        Campaign.query.filter_by(master_id=current_user.id)
        .order_by(Campaign.created_at.desc())
        .all()
    )
    playing = [
        m.campaign
        for m in current_user.memberships.all()
        if m.campaign and m.campaign.master_id != current_user.id
    ]
    characters = (
        Character.query.filter_by(owner_id=current_user.id, kind="pj")
        .order_by(Character.updated_at.desc())
        .limit(8)
        .all()
    )

    from app import reminders
    pending = [(item, campaign, reminders.when_label(item))
               for item, campaign in reminders.pending_for(current_user)]
    campaign_ids = [c.id for c in mastering] + [c.id for c in playing]
    upcoming = []
    if campaign_ids:
        upcoming = (
            GameSession.query.filter(
                GameSession.campaign_id.in_(campaign_ids),
                GameSession.status == "planejada",
            )
            .order_by(GameSession.scheduled_for.is_(None), GameSession.scheduled_for.asc())
            .limit(5)
            .all()
        )

    return render_template(
        "main/dashboard.html",
        attendance_statuses=SessionAttendance.STATUSES,
        pending=pending,
        mastering=mastering,
        playing=playing,
        characters=characters,
        upcoming=upcoming,
        today=date.today(),
    )
