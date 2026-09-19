# -*- coding: utf-8 -*-
"""Ferramentas da mesa: relógios de progresso, "mostrar para a mesa", tesouro
do grupo e calendário do mundo.

Tudo que precisa atualizar na tela dos outros (relógios, handout, tesouro)
chega pela consulta única de app/blueprints/live.py.
"""
from datetime import datetime, timedelta

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required

from app import security
from app import treasure as treasure_helper
from app import worldcal
from app.cas import ConflictError, update_json
from app.extensions import db
from app.models import Asset, Clock, GameSession, Note, TimelineEntry
from app.utils import clean_color, rich_text, to_int

bp = Blueprint("table", __name__, url_prefix="/campanhas")

SPOTLIGHT_TTL = timedelta(minutes=20)
MAX_CLOCKS = 30


def _campaign(campaign_id, master_only=False):
    from app.blueprints.campaigns import get_campaign
    return get_campaign(campaign_id, master_only=master_only)


@bp.app_context_processor
def table_helpers():
    """Funções que os templates das campanhas usam (relógios e datas do mundo)."""
    def world_parts(cal, ordinal):
        return worldcal.from_ordinal(cal, ordinal) if cal and ordinal is not None else None
    return {"clock_list": clocks_payload, "world_date": date_label, "world_calendar": calendar_of,
            "world_parts": world_parts}


# ======================================================== relógios de progresso
def clocks_payload(campaign, is_master):
    query = campaign.clocks
    if not is_master:
        query = query.filter(Clock.visibility == "mesa")
    return [c.as_dict() for c in query.all()]


def _clock_fields(clock, data):
    if "title" in data:
        title = str(data.get("title") or "").strip()[:120]
        if not title:
            raise ValueError("Dê um nome ao relógio.")
        clock.title = title
    if "segments" in data:
        clock.segments = max(2, min(24, to_int(data.get("segments"), clock.segments or 6)))
    if "visibility" in data and data.get("visibility") in Clock.VISIBILITY:
        clock.visibility = data["visibility"]
    if "color" in data:
        clock.color = clean_color(data.get("color"), clock.color or "#f0a94b")
    if "filled" in data:
        clock.filled = to_int(data.get("filled"), clock.filled or 0)
    if "delta" in data:
        clock.filled = (clock.filled or 0) + to_int(data.get("delta"), 0)
    clock.filled = max(0, min(clock.segments, clock.filled or 0))


@bp.route("/<int:campaign_id>/relogios", methods=["POST"])
@login_required
def clock_create(campaign_id):
    campaign = _campaign(campaign_id, master_only=True)
    if campaign.clocks.count() >= MAX_CLOCKS:
        return jsonify({"ok": False, "message": "No máximo %d relógios." % MAX_CLOCKS}), 400
    data = request.get_json(silent=True) or {}
    clock = Clock(campaign_id=campaign.id, title="?", segments=6, filled=0,
                  position=campaign.clocks.count())
    try:
        _clock_fields(clock, dict({"title": "", "segments": 6, "visibility": "mesa"}, **data))
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    db.session.add(clock)
    db.session.commit()
    return jsonify({"ok": True, "clocks": clocks_payload(campaign, True)})


@bp.route("/<int:campaign_id>/relogios/<int:clock_id>", methods=["POST"])
@login_required
def clock_update(campaign_id, clock_id):
    campaign = _campaign(campaign_id, master_only=True)
    clock = Clock.query.filter_by(id=clock_id, campaign_id=campaign.id).first_or_404()
    data = request.get_json(silent=True) or {}
    if data.get("delete"):
        db.session.delete(clock)
    else:
        try:
            _clock_fields(clock, data)
        except ValueError as error:
            return jsonify({"ok": False, "message": str(error)}), 400
    db.session.commit()
    return jsonify({"ok": True, "clocks": clocks_payload(campaign, True)})


# ========================================================= mostrar para a mesa
def spotlight_payload(campaign):
    """O handout aberto agora, ou None. Só conteúdo que a mesa pode ver."""
    spot = campaign.spotlight
    if not isinstance(spot, dict) or not spot.get("seq"):
        return None
    try:
        at = datetime.strptime(spot.get("at", ""), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    if datetime.utcnow() - at > SPOTLIGHT_TTL:
        return None
    data = {"seq": spot["seq"], "kind": spot.get("kind"), "by": spot.get("by"),
            "at": spot["at"] + "Z"}
    if spot.get("kind") == "mapa":
        asset = Asset.query.filter_by(id=spot.get("id"), campaign_id=campaign.id).first()
        if asset is None or asset.visibility != "mesa":
            return None
        data.update(title=asset.title or "Imagem", image=asset.url)
    elif spot.get("kind") == "anotacao":
        note = Note.query.filter_by(id=spot.get("id"), campaign_id=campaign.id).first()
        if note is None or note.visibility != "mesa":
            return None
        data.update(title=note.title, html=str(rich_text(note.body)))
    else:
        return None
    return data


@bp.route("/<int:campaign_id>/mostrar", methods=["POST"])
@login_required
def spotlight(campaign_id):
    """Revela a imagem ou anotação para a mesa toda e abre na tela de todos."""
    campaign = _campaign(campaign_id, master_only=True)
    kind = request.form.get("kind")
    item_id = to_int(request.form.get("id"), 0)
    if kind == "mapa":
        item = Asset.query.filter_by(id=item_id, campaign_id=campaign.id, kind="mapa").first_or_404()
        item.visibility = "mesa"
        title = item.title or "a imagem"
        back = url_for("uploads.gallery", campaign_id=campaign.id)
    elif kind == "anotacao":
        item = Note.query.filter_by(id=item_id, campaign_id=campaign.id).first_or_404()
        if item.visibility != "mesa":
            item.visibility = "mesa"
            item.recipients = []
            item.revealed_at = datetime.utcnow()
        title = item.title
        back = url_for("campaigns.notes", campaign_id=campaign.id)
    else:
        abort(400)
    previous = campaign.spotlight if isinstance(campaign.spotlight, dict) else {}
    campaign.spotlight = {
        "seq": to_int(previous.get("seq"), 0) + 1, "kind": kind, "id": item.id,
        "by": current_user.id, "at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    db.session.commit()
    flash("“%s” apareceu na tela de toda a mesa." % title, "success")
    return redirect(security.safe_next(request.form.get("next"), back))


# =============================================================== tesouro do grupo
def _party(campaign):
    return {c.id: c.name for c in campaign.characters.filter_by(kind="pj").order_by("name")}


def treasure_payload(campaign):
    data = treasure_helper.normalize(campaign.treasure)
    coins = treasure_helper.currencies(campaign.system)
    return {
        "items": data["items"],
        "coins": [dict(c, amount=data["coins"].get(c["key"], 0)) for c in coins],
        "log": data["log"],
        "weight": treasure_helper.total_weight(data),
        "unit": ((campaign.system.data or {}).get("inventory") or {}).get("unit") or "",
        "party": [{"id": cid, "name": name} for cid, name in _party(campaign).items()],
    }


@bp.route("/<int:campaign_id>/tesouro")
@login_required
def treasure(campaign_id):
    from app.blueprints.campaigns import get_campaign
    campaign = get_campaign(campaign_id)
    return render_template("campaigns/treasure.html", campaign=campaign,
                           is_master=campaign.is_master(current_user),
                           payload=treasure_payload(campaign))


@bp.route("/<int:campaign_id>/tesouro", methods=["POST"])
@login_required
def treasure_change(campaign_id):
    """Qualquer um da mesa mexe no tesouro; toda movimentação fica registrada."""
    campaign = _campaign(campaign_id)
    payload = request.get_json(silent=True) or {}
    coins = treasure_helper.currencies(campaign.system)
    party = _party(campaign)

    def change(data):
        return treasure_helper.apply(data, payload, current_user.username, coins, party)

    try:
        update_json("campaigns", "treasure", campaign.id, change,
                    treasure_helper.normalize, obj=campaign)
    except (treasure_helper.TreasureError, ConflictError) as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    return jsonify({"ok": True, "treasure": treasure_payload(campaign)})


# ============================================================ calendário do mundo
def calendar_of(campaign):
    return worldcal.normalize(campaign.calendar)


def date_label(campaign, ordinal, with_weekday=False):
    return worldcal.format_date(calendar_of(campaign), ordinal, with_weekday)


@bp.route("/<int:campaign_id>/calendario")
@login_required
def calendar(campaign_id):
    from app.blueprints.campaigns import get_campaign
    campaign = get_campaign(campaign_id)
    is_master = campaign.is_master(current_user)
    cal = calendar_of(campaign)
    if cal is None:
        return render_template("campaigns/calendar.html", campaign=campaign, is_master=is_master,
                               cal=None, presets=worldcal.PRESETS)

    today = worldcal.from_ordinal(cal, cal["today"])
    year = max(1, min(worldcal.MAX_YEAR, to_int(request.args.get("ano"), today[0])))
    month = to_int(request.args.get("mes"), today[1])
    if not 1 <= month <= len(cal["months"]):
        month = today[1]
    grid = worldcal.month_grid(cal, year, month)
    first = worldcal.to_ordinal(cal, year, month, 1)
    last = first + cal["months"][month - 1]["days"] - 1

    events = {}
    for entry in campaign.timeline.filter(TimelineEntry.world_day.between(first, last)):
        events.setdefault(entry.world_day, []).append(
            {"kind": "evento", "title": entry.title,
             "url": url_for("campaigns.timeline", campaign_id=campaign.id) + "#t%d" % entry.id})
    for item in campaign.sessions.filter(GameSession.world_day.between(first, last)):
        events.setdefault(item.world_day, []).append(
            {"kind": "sessao", "title": "Sessão %d · %s" % (item.number, item.title),
             "url": url_for("campaigns.session_detail", campaign_id=campaign.id,
                            session_id=item.id)})

    prev_month = (year, month - 1) if month > 1 else (year - 1, len(cal["months"]))
    next_month = (year, month + 1) if month < len(cal["months"]) else (year + 1, 1)
    upcoming = (campaign.timeline.filter(TimelineEntry.world_day.isnot(None))
                .order_by(TimelineEntry.world_day.desc()).limit(8).all())
    return render_template(
        "campaigns/calendar.html", campaign=campaign, is_master=is_master, cal=cal,
        presets=worldcal.PRESETS, year=year, month=month, grid=grid, events=events,
        today=cal["today"], today_label=worldcal.format_date(cal, cal["today"], True),
        prev_month=prev_month if prev_month[0] >= 1 else None, next_month=next_month,
        recent=upcoming, fmt=lambda o: worldcal.format_date(cal, o),
    )


@bp.route("/<int:campaign_id>/calendario", methods=["POST"])
@login_required
def calendar_change(campaign_id):
    campaign = _campaign(campaign_id, master_only=True)
    action = request.form.get("action")
    cal = calendar_of(campaign)
    back = url_for("table.calendar", campaign_id=campaign.id)
    try:
        if action == "setup":
            preset = request.form.get("preset")
            era = (request.form.get("era") or "").strip()[:20]
            # Ano de "hoje": o informado; sem ele, o ano atual do calendário antigo.
            year = to_int(request.form.get("year"), 0)
            if not year:
                year = worldcal.from_ordinal(cal, cal["today"])[0] if cal else 1
            if preset == "personalizado":
                months = worldcal.parse_months(request.form.get("months"))
                weekdays = [w.strip() for w in (request.form.get("weekdays") or "").split(",")]
                new = worldcal.normalize({"months": months, "weekdays": weekdays, "era": era})
            else:
                new = worldcal.from_preset(preset, era)
            new["today"] = worldcal.to_ordinal(new, year, 1, 1)
            campaign.calendar = new
            flash("Calendário configurado.", "success")
        elif cal is None:
            raise worldcal.CalendarError("Configure o calendário primeiro.")
        elif action == "advance":
            days = max(-3650, min(3650, to_int(request.form.get("days"), 0)))
            cal["today"] = max(0, cal["today"] + days)
            campaign.calendar = cal
            flash("Hoje no mundo: %s." % worldcal.format_date(cal, cal["today"], True), "success")
        elif action == "set":
            cal["today"] = worldcal.to_ordinal(cal, request.form.get("year"),
                                               request.form.get("month"), request.form.get("day"))
            campaign.calendar = cal
            flash("Hoje no mundo: %s." % worldcal.format_date(cal, cal["today"], True), "success")
        elif action == "clear":
            campaign.calendar = None
            flash("Calendário removido. As datas das entradas ficam guardadas.", "success")
        else:
            abort(400)
    except worldcal.CalendarError as error:
        flash(str(error), "error")
        return redirect(back)
    db.session.commit()
    year, month, _ = worldcal.from_ordinal(campaign.calendar, campaign.calendar["today"]) \
        if campaign.calendar else (None, None, None)
    return redirect(url_for("table.calendar", campaign_id=campaign.id, ano=year, mes=month)
                    if year else back)
