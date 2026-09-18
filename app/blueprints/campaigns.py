# -*- coding: utf-8 -*-
import copy
import secrets
from datetime import date, datetime

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, send_file, url_for)
from flask_login import current_user, login_required
from sqlalchemy import and_, or_

from app import dice
from app import security
from app import sheet as sheet_helper
from app.blueprints.uploads import remove_file
from app.extensions import db
from app.models import (Campaign, CampaignMember, Character, Encounter, GameSession,
                        GameSystem, Note, NoteRecipient, RollLog, SessionAttendance,
                        TimelineEntry, User)
from app.utils import slugify, to_int

bp = Blueprint("campaigns", __name__, url_prefix="/campanhas")

NOTE_CATEGORIES = [
    ("geral", "Geral"),
    ("trama", "Trama / Arco"),
    ("pessoa", "Pessoa / NPC"),
    ("lugar", "Lugar"),
    ("faccao", "Facção"),
    ("item", "Item / Relíquia"),
    ("segredo", "Segredo"),
    ("regra", "Regra da mesa"),
]

SESSION_STATUS = [
    ("planejada", "Planejada"),
    ("realizada", "Realizada"),
    ("cancelada", "Cancelada"),
]

MAX_SPAWN = 20


# --------------------------------------------------------------- helpers
def get_campaign(campaign_id, master_only=False):
    campaign = db.get_or_404(Campaign, campaign_id)
    if master_only:
        if not campaign.is_master(current_user):
            abort(403)
    elif not campaign.can_view(current_user):
        abort(403)
    return campaign


def parse_date(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_time(value):
    value = (value or "").strip()
    try:
        return datetime.strptime(value, "%H:%M").strftime("%H:%M") if value else None
    except ValueError:
        return None


def parse_beats(raw_lines, previous=None):
    """Converte o textarea de cenas em checklist preservando o que já estava feito."""
    done_map = {b.get("text"): b.get("done") for b in (previous or [])}
    beats = []
    for line in (raw_lines or "").splitlines():
        text = line.strip().lstrip("-").strip()
        if text:
            beats.append({"text": text[:200], "done": bool(done_map.get(text))})
    return beats


def visible_notes(campaign, user, is_master):
    """Anotações que este usuário pode ler. Usado em toda listagem de notas."""
    query = campaign.notes
    if is_master:
        return query
    return query.filter(
        or_(
            Note.visibility == "mesa",
            Note.author_id == user.id,
            and_(Note.visibility == "jogadores",
                 Note.recipients.any(NoteRecipient.user_id == user.id)),
        )
    )


def players_of(campaign):
    """Membros da mesa que não são o mestre."""
    return [m.user for m in campaign.members.all()
            if m.user and m.user_id != campaign.master_id]


# --------------------------------------------------------------- campanha
@bp.route("/nova", methods=["GET", "POST"])
@login_required
def create():
    systems = GameSystem.query.filter(
        (GameSystem.is_preset.is_(True)) | (GameSystem.owner_id == current_user.id)
    ).order_by(GameSystem.is_preset.desc(), GameSystem.name).all()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        system_id = to_int(request.form.get("system_id"))
        system = db.session.get(GameSystem, system_id) if system_id else None
        if not name:
            flash("Dê um nome à campanha.", "error")
        elif system is None or not system.usable_by(current_user):
            flash("Escolha um sistema válido.", "error")
        else:
            campaign = Campaign(
                name=name,
                tagline=(request.form.get("tagline") or "").strip(),
                description=(request.form.get("description") or "").strip(),
                system_id=system.id,
                master_id=current_user.id,
                invite_code=Campaign.new_invite_code(),
            )
            db.session.add(campaign)
            db.session.flush()
            db.session.add(
                CampaignMember(campaign_id=campaign.id, user_id=current_user.id, role="mestre")
            )
            db.session.commit()
            flash("Campanha criada! Compartilhe o código de convite com a mesa.", "success")
            return redirect(url_for("campaigns.overview", campaign_id=campaign.id))

    return render_template("campaigns/new.html", systems=systems)


def find_by_invite(code):
    """Campanha do código de convite. Devolve (campanha, segundos_de_espera).

    Códigos errados contam por IP (ver app/security.py): quem ficar chutando
    códigos é bloqueado bem antes de achar uma campanha por sorte.
    """
    key = "convite:" + security.client_ip()
    wait = security.seconds_blocked(None, key)
    if wait:
        return None, wait
    code = (code or "").strip().upper()
    campaign = Campaign.query.filter_by(invite_code=code).first() if code else None
    if campaign is None:
        security.record_attempt("convite", key, success=False)
    return campaign, 0


def add_member(campaign):
    if campaign.membership(current_user):
        flash("Você já faz parte desta campanha.", "warning")
    else:
        db.session.add(
            CampaignMember(campaign_id=campaign.id, user_id=current_user.id, role="jogador")
        )
        db.session.commit()
        flash("Você entrou em %s." % campaign.name, "success")
    return redirect(url_for("campaigns.overview", campaign_id=campaign.id))


@bp.route("/entrar", methods=["POST"])
@login_required
def join():
    campaign, wait = find_by_invite(request.form.get("invite_code"))
    if wait:
        flash(security.wait_message(wait), "error")
        return redirect(url_for("main.dashboard"))
    if not campaign:
        flash("Código de convite não encontrado.", "error")
        return redirect(url_for("main.dashboard"))
    return add_member(campaign)


@bp.route("/convite/<code>", methods=["GET", "POST"])
def invite(code):
    """Link de convite. Abrir o link só mostra a campanha; entrar exige confirmar
    (POST) — ninguém vai parar numa mesa só por clicar num link."""
    campaign, wait = find_by_invite(code)
    if wait:
        flash(security.wait_message(wait), "error")
        return render_template("campaigns/invite.html", campaign=None), 429
    if campaign is None:
        return render_template("campaigns/invite.html", campaign=None), 404

    if not current_user.is_authenticated:
        return render_template("campaigns/invite.html", campaign=campaign, need_login=True)
    if campaign.can_view(current_user):
        flash("Você já faz parte desta campanha.", "warning")
        return redirect(url_for("campaigns.overview", campaign_id=campaign.id))
    if request.method == "POST":
        return add_member(campaign)
    return render_template("campaigns/invite.html", campaign=campaign, need_login=False)


@bp.route("/<int:campaign_id>")
@login_required
def overview(campaign_id):
    campaign = get_campaign(campaign_id)
    is_master = campaign.is_master(current_user)

    characters = campaign.characters.filter_by(kind="pj").all()
    sessions = campaign.sessions.order_by(GameSession.number.desc()).limit(4).all()
    pinned = (visible_notes(campaign, current_user, is_master)
              .filter(Note.pinned.is_(True))
              .order_by(Note.updated_at.desc()).limit(6).all())
    revealed = []
    if not is_master:
        revealed = (visible_notes(campaign, current_user, is_master)
                    .filter(Note.revealed_at.isnot(None))
                    .order_by(Note.revealed_at.desc()).limit(4).all())
        revealed = [n for n in revealed if n.recently_revealed]
    timeline = campaign.timeline.order_by(TimelineEntry.created_at.desc()).limit(5).all()

    return render_template(
        "campaigns/overview.html",
        campaign=campaign,
        is_master=is_master,
        characters=characters,
        sessions=sessions,
        pinned=pinned,
        revealed=revealed,
        timeline=timeline,
        today=date.today(),
    )


@bp.route("/<int:campaign_id>/editar", methods=["GET", "POST"])
@login_required
def edit(campaign_id):
    campaign = get_campaign(campaign_id, master_only=True)
    if request.method == "POST":
        campaign.name = (request.form.get("name") or campaign.name).strip()
        campaign.tagline = (request.form.get("tagline") or "").strip()
        campaign.description = (request.form.get("description") or "").strip()
        status = request.form.get("status")
        if status in ("ativa", "pausada", "concluida"):
            campaign.status = status
        db.session.commit()
        flash("Campanha atualizada.", "success")
        return redirect(url_for("campaigns.overview", campaign_id=campaign.id))
    return render_template("campaigns/edit.html", campaign=campaign)


@bp.route("/<int:campaign_id>/exportar")
@login_required
def export(campaign_id):
    """Baixa a campanha inteira num ZIP (JSON + imagens). Só o mestre."""
    from app.export import build_zip

    campaign = get_campaign(campaign_id, master_only=True)
    filename = "campanha-%s-%s.zip" % (slugify(campaign.name, "campanha"), date.today().isoformat())
    response = send_file(build_zip(campaign), mimetype="application/zip",
                         as_attachment=True, download_name=filename)
    # Tem os segredos do mestre: nada de cache em proxy ou navegador compartilhado.
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.route("/<int:campaign_id>/excluir", methods=["POST"])
@login_required
def delete(campaign_id):
    campaign = get_campaign(campaign_id, master_only=True)
    # O cascade apaga as linhas; os arquivos no disco saem à mão.
    for asset in campaign.assets.all():
        remove_file(asset)
    db.session.delete(campaign)
    db.session.commit()
    flash("Campanha excluída.", "success")
    return redirect(url_for("main.dashboard"))


# --------------------------------------------------------------- membros
@bp.route("/<int:campaign_id>/mesa")
@login_required
def members(campaign_id):
    campaign = get_campaign(campaign_id)
    roster = campaign.members.all()
    chars = {}
    for character in campaign.characters.filter_by(kind="pj").all():
        chars.setdefault(character.owner_id, []).append(character)
    return render_template(
        "campaigns/members.html",
        campaign=campaign,
        is_master=campaign.is_master(current_user),
        roster=roster,
        chars=chars,
    )


@bp.route("/<int:campaign_id>/mesa/<int:member_id>/remover", methods=["POST"])
@login_required
def remove_member(campaign_id, member_id):
    campaign = get_campaign(campaign_id, master_only=True)
    member = CampaignMember.query.filter_by(id=member_id, campaign_id=campaign.id).first_or_404()
    if member.user_id == campaign.master_id:
        flash("O mestre não pode sair da própria campanha.", "error")
    else:
        db.session.delete(member)
        db.session.commit()
        flash("Jogador removido da mesa.", "success")
    return redirect(url_for("campaigns.members", campaign_id=campaign.id))


@bp.route("/<int:campaign_id>/mesa/novo-codigo", methods=["POST"])
@login_required
def new_code(campaign_id):
    campaign = get_campaign(campaign_id, master_only=True)
    campaign.invite_code = Campaign.new_invite_code()
    db.session.commit()
    flash("Novo código gerado. O anterior deixou de funcionar.", "success")
    return redirect(url_for("campaigns.members", campaign_id=campaign.id))


@bp.route("/<int:campaign_id>/sair", methods=["POST"])
@login_required
def leave(campaign_id):
    campaign = db.get_or_404(Campaign, campaign_id)
    member = campaign.membership(current_user)
    if campaign.is_master(current_user):
        flash("Você é o mestre. Exclua a campanha se quiser encerrá-la.", "error")
        return redirect(url_for("campaigns.overview", campaign_id=campaign.id))
    if member:
        db.session.delete(member)
        db.session.commit()
        flash("Você saiu da campanha.", "success")
    return redirect(url_for("main.dashboard"))


# --------------------------------------------------------------- sessões
@bp.route("/<int:campaign_id>/sessoes")
@login_required
def sessions(campaign_id):
    campaign = get_campaign(campaign_id)
    items = campaign.sessions.order_by(
        GameSession.scheduled_for.is_(None), GameSession.scheduled_for.asc(), GameSession.number
    ).all()
    return render_template(
        "campaigns/sessions.html",
        campaign=campaign,
        is_master=campaign.is_master(current_user),
        sessions=items,
        statuses=SESSION_STATUS,
        today=date.today(),
        player_count=len(players_of(campaign)),
    )


@bp.route("/<int:campaign_id>/sessoes/nova", methods=["POST"])
@login_required
def session_create(campaign_id):
    campaign = get_campaign(campaign_id, master_only=True)
    last = campaign.sessions.order_by(GameSession.number.desc()).first()
    item = GameSession(
        campaign_id=campaign.id,
        number=(last.number + 1) if last else 1,
        title=(request.form.get("title") or "").strip() or "Nova sessão",
        scheduled_for=parse_date(request.form.get("scheduled_for")),
        start_time=parse_time(request.form.get("start_time")),
        beats=[],
    )
    db.session.add(item)
    db.session.commit()
    return redirect(url_for("campaigns.session_detail", campaign_id=campaign.id, session_id=item.id))


@bp.route("/<int:campaign_id>/sessoes/<int:session_id>", methods=["GET", "POST"])
@login_required
def session_detail(campaign_id, session_id):
    campaign = get_campaign(campaign_id)
    item = GameSession.query.filter_by(id=session_id, campaign_id=campaign.id).first_or_404()
    is_master = campaign.is_master(current_user)

    if request.method == "POST":
        if not is_master:
            abort(403)
        item.title = (request.form.get("title") or item.title).strip()
        item.number = to_int(request.form.get("number"), item.number)
        item.scheduled_for = parse_date(request.form.get("scheduled_for"))
        item.start_time = parse_time(request.form.get("start_time"))
        status = request.form.get("status")
        if status in dict(SESSION_STATUS):
            item.status = status
        item.synopsis = (request.form.get("synopsis") or "").strip()
        item.plan = (request.form.get("plan") or "").strip()
        item.recap = (request.form.get("recap") or "").strip()
        item.beats = parse_beats(request.form.get("beats"), item.beats)
        db.session.commit()
        flash("Sessão salva.", "success")
        return redirect(
            url_for("campaigns.session_detail", campaign_id=campaign.id, session_id=item.id)
        )

    answers = {a.user_id: a for a in item.attendance.all()}
    roster = [{"user": user, "answer": answers.get(user.id)} for user in players_of(campaign)]
    return render_template(
        "campaigns/session_detail.html",
        campaign=campaign,
        session=item,
        is_master=is_master,
        statuses=SESSION_STATUS,
        attendance_statuses=SessionAttendance.STATUSES,
        roster=roster,
        my_answer=answers.get(current_user.id),
    )


@bp.route("/<int:campaign_id>/sessoes/<int:session_id>/presenca", methods=["POST"])
@login_required
def session_attendance(campaign_id, session_id):
    campaign = get_campaign(campaign_id)
    item = GameSession.query.filter_by(id=session_id, campaign_id=campaign.id).first_or_404()
    status = request.form.get("status")
    if status not in dict(SessionAttendance.STATUSES):
        flash("Escolha uma resposta.", "error")
    else:
        answer = item.attendance_of(current_user)
        if answer is None:
            answer = SessionAttendance(session_id=item.id, user_id=current_user.id)
            db.session.add(answer)
        answer.status = status
        answer.comment = (request.form.get("comment") or "").strip()[:200]
        db.session.commit()
        flash("Presença registrada: %s." % answer.label, "success")
    return redirect(url_for("campaigns.session_detail", campaign_id=campaign.id, session_id=item.id))


@bp.route("/<int:campaign_id>/sessoes/<int:session_id>/cena", methods=["POST"])
@login_required
def session_beat(campaign_id, session_id):
    campaign = get_campaign(campaign_id, master_only=True)
    item = GameSession.query.filter_by(id=session_id, campaign_id=campaign.id).first_or_404()
    index = to_int((request.get_json(silent=True) or {}).get("index"), -1)
    # deepcopy: o SQLAlchemy só detecta a mudança se o valor atribuído for novo.
    beats = copy.deepcopy(item.beats or [])
    if 0 <= index < len(beats):
        beats[index]["done"] = not beats[index].get("done")
        item.beats = beats
        db.session.commit()
        return jsonify({"ok": True, "done": beats[index]["done"], "progress": item.progress})
    return jsonify({"ok": False}), 400


@bp.route("/<int:campaign_id>/sessoes/<int:session_id>/xp", methods=["POST"])
@login_required
def session_xp(campaign_id, session_id):
    """Distribui XP para todos os personagens jogadores da campanha de uma vez."""
    campaign = get_campaign(campaign_id, master_only=True)
    item = GameSession.query.filter_by(id=session_id, campaign_id=campaign.id).first_or_404()

    amount = to_int(request.form.get("amount"), 0)
    note = (request.form.get("note") or "").strip() or "Sessão #%d — %s" % (item.number, item.title)
    if not amount:
        flash("Informe quanto de experiência distribuir.", "error")
        return redirect(
            url_for("campaigns.session_detail", campaign_id=campaign.id, session_id=item.id)
        )

    party = campaign.characters.filter_by(kind="pj").all()
    for character in party:
        data = sheet_helper.normalize(copy.deepcopy(character.data))
        data["xp"] = max(0, to_int(data.get("xp"), 0) + amount)
        data["progress"].append(
            {
                "name": note[:120],
                "amount": amount,
                "desc": "",
                "at": (item.scheduled_for or date.today()).isoformat(),
            }
        )
        character.data = data
        character._revision_reason = "xp da sessão"
        # Mudança feita por outra pessoa: a ficha aberta do jogador precisa saber.
        character.bump_version()
    db.session.commit()

    if party:
        flash("%+d de experiência para %d personagem(ns)." % (amount, len(party)), "success")
    else:
        flash("Nenhum personagem jogador nesta campanha ainda.", "warning")
    return redirect(
        url_for("campaigns.session_detail", campaign_id=campaign.id, session_id=item.id)
    )


@bp.route("/<int:campaign_id>/sessoes/<int:session_id>/excluir", methods=["POST"])
@login_required
def session_delete(campaign_id, session_id):
    campaign = get_campaign(campaign_id, master_only=True)
    item = GameSession.query.filter_by(id=session_id, campaign_id=campaign.id).first_or_404()
    db.session.delete(item)
    db.session.commit()
    flash("Sessão removida.", "success")
    return redirect(url_for("campaigns.sessions", campaign_id=campaign.id))


# --------------------------------------------------------------- anotações
@bp.route("/<int:campaign_id>/anotacoes")
@login_required
def notes(campaign_id):
    campaign = get_campaign(campaign_id)
    is_master = campaign.is_master(current_user)
    query = visible_notes(campaign, current_user, is_master)

    category = request.args.get("categoria")
    if category and category in dict(NOTE_CATEGORIES):
        query = query.filter(Note.category == category)
    search = (request.args.get("q") or "").strip()
    if search:
        like = "%%%s%%" % search
        query = query.filter(
            db.or_(Note.title.ilike(like), Note.body.ilike(like), Note.tags.ilike(like))
        )

    items = query.order_by(Note.pinned.desc(), Note.updated_at.desc()).all()
    return render_template(
        "campaigns/notes.html",
        campaign=campaign,
        is_master=is_master,
        notes=items,
        categories=NOTE_CATEGORIES,
        active_category=category,
        search=search,
    )


def set_recipients(note, campaign, user_ids):
    """Troca os destinatários de uma nota por jogadores válidos da campanha."""
    valid = {u.id for u in players_of(campaign)}
    wanted = {uid for uid in user_ids if uid in valid}
    note.recipients = [r for r in note.recipients if r.user_id in wanted]
    have = {r.user_id for r in note.recipients}
    for uid in wanted - have:
        note.recipients.append(NoteRecipient(user_id=uid))
    return wanted


@bp.route("/<int:campaign_id>/anotacoes/nova", methods=["GET", "POST"])
@bp.route("/<int:campaign_id>/anotacoes/<int:note_id>/editar", methods=["GET", "POST"])
@login_required
def note_form(campaign_id, note_id=None):
    campaign = get_campaign(campaign_id)
    is_master = campaign.is_master(current_user)

    note = None
    if note_id:
        note = Note.query.filter_by(id=note_id, campaign_id=campaign.id).first_or_404()
        if not note.visible_to(current_user, is_master):
            abort(404)
        can_edit = note.author_id == current_user.id or is_master
        if request.method == "POST" and not can_edit:
            abort(403)
    else:
        can_edit = True

    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("A anotação precisa de um título.", "error")
        else:
            if note is None:
                note = Note(campaign_id=campaign.id, author_id=current_user.id)
                db.session.add(note)
            note.title = title
            note.body = (request.form.get("body") or "").strip()
            category = request.form.get("category")
            note.category = category if category in dict(NOTE_CATEGORIES) else "geral"
            note.tags = (request.form.get("tags") or "").strip()[:240]
            note.pinned = bool(request.form.get("pinned"))

            visibility = request.form.get("visibility")
            previous = note.visibility
            if is_master and visibility in ("mestre", "jogadores"):
                note.visibility = visibility
            else:
                note.visibility = "mesa"
            if note.visibility == "jogadores":
                chosen = set_recipients(
                    note, campaign, [to_int(v) for v in request.form.getlist("recipients")]
                )
                if not chosen:
                    note.visibility = "mestre"
                    flash("Nenhum jogador escolhido: a anotação ficou só para o mestre.", "warning")
            else:
                note.recipients = []
            if previous == "mestre" and note.visibility != "mestre":
                note.revealed_at = datetime.utcnow()

            db.session.commit()
            flash("Anotação salva.", "success")
            return redirect(url_for("campaigns.notes", campaign_id=campaign.id))

    return render_template(
        "campaigns/note_form.html",
        campaign=campaign,
        is_master=is_master,
        can_edit=can_edit,
        note=note,
        categories=NOTE_CATEGORIES,
        players=players_of(campaign),
    )


@bp.route("/<int:campaign_id>/anotacoes/<int:note_id>/revelar", methods=["POST"])
@login_required
def note_reveal(campaign_id, note_id):
    """Mostra uma anotação secreta para a mesa toda ou para jogadores escolhidos."""
    campaign = get_campaign(campaign_id, master_only=True)
    note = Note.query.filter_by(id=note_id, campaign_id=campaign.id).first_or_404()

    target = request.form.get("target", "mesa")
    if target == "mestre":
        note.visibility = "mestre"
        note.recipients = []
        note.revealed_at = None
        message = "“%s” voltou a ser só do mestre." % note.title
    elif target == "jogadores":
        chosen = set_recipients(note, campaign, [to_int(v) for v in request.form.getlist("recipients")])
        if not chosen:
            flash("Escolha pelo menos um jogador para revelar.", "error")
            return redirect(request.referrer or url_for("campaigns.notes", campaign_id=campaign.id))
        note.visibility = "jogadores"
        note.revealed_at = datetime.utcnow()
        names = [u.username for u in players_of(campaign) if u.id in chosen]
        message = "“%s” revelada para %s." % (note.title, ", ".join(names))
    else:
        note.visibility = "mesa"
        note.recipients = []
        note.revealed_at = datetime.utcnow()
        message = "“%s” revelada para a mesa toda." % note.title

    db.session.commit()
    flash(message, "success")
    return redirect(request.referrer or url_for("campaigns.notes", campaign_id=campaign.id))


@bp.route("/<int:campaign_id>/anotacoes/<int:note_id>/fixar", methods=["POST"])
@login_required
def note_pin(campaign_id, note_id):
    campaign = get_campaign(campaign_id)
    note = Note.query.filter_by(id=note_id, campaign_id=campaign.id).first_or_404()
    if note.author_id != current_user.id and not campaign.is_master(current_user):
        abort(403)
    note.pinned = not note.pinned
    db.session.commit()
    return redirect(request.referrer or url_for("campaigns.notes", campaign_id=campaign.id))


@bp.route("/<int:campaign_id>/anotacoes/<int:note_id>/excluir", methods=["POST"])
@login_required
def note_delete(campaign_id, note_id):
    campaign = get_campaign(campaign_id)
    note = Note.query.filter_by(id=note_id, campaign_id=campaign.id).first_or_404()
    if note.author_id != current_user.id and not campaign.is_master(current_user):
        abort(403)
    db.session.delete(note)
    db.session.commit()
    flash("Anotação removida.", "success")
    return redirect(url_for("campaigns.notes", campaign_id=campaign.id))


# --------------------------------------------------------------- elenco e bestiário
@bp.route("/<int:campaign_id>/elenco")
@login_required
def cast(campaign_id):
    campaign = get_campaign(campaign_id)
    is_master = campaign.is_master(current_user)
    query = campaign.characters.filter(Character.kind != "pj")
    if not is_master:
        query = query.filter(Character.visible_to_players.is_(True))
    return render_template(
        "campaigns/cast.html",
        campaign=campaign,
        is_master=is_master,
        cast=query.order_by(Character.kind.desc(), Character.name).all(),
        encounters=(campaign.encounters.filter_by(active=True)
                    .order_by(Encounter.created_at.desc()).all() if is_master else []),
    )


# --------------------------------------------------------------- combate
def hp_bar_key(system):
    """A primeira barra do sistema é a de vida no combate (PV, Vitalidade...)."""
    bars = system.bars
    return bars[0]["key"] if bars else None


def health_state(hp, hp_max):
    if hp_max <= 0:
        return "?"
    if hp <= 0:
        return "caído"
    ratio = hp / float(hp_max)
    if ratio >= 1:
        return "ileso"
    if ratio > 0.5:
        return "ferido"
    return "grave"


def encounter_state(encounter, is_master, messages=None):
    """Combatentes com PV e condições lidos das fichas ligadas.

    Para jogadores, inimigos não levam PV nem notas — só um estado geral. O
    número não vai na resposta, então não aparece nem no DevTools.
    """
    campaign = encounter.campaign
    combatants = list(encounter.combatants or [])
    ids = {c.get("character_id") for c in combatants if c.get("character_id")}
    sheets = {}
    if ids:
        sheets = {ch.id: ch for ch in Character.query.filter(
            Character.id.in_(ids), Character.campaign_id == campaign.id)}
    key = hp_bar_key(campaign.system)

    out = []
    for raw in combatants:
        c = dict(raw)
        sheet = sheets.get(c.get("character_id"))
        c["conditions"] = []
        c["kind"] = c.get("kind") or ("criatura" if c.get("is_npc") else "pj")
        if sheet is not None:
            data, _ = sheet_helper.apply_formulas(campaign.system, sheet.data)
            bar = data["bars"].get(key) or {}
            c["name"] = sheet.name
            c["kind"] = sheet.kind
            c["hp"] = to_int(bar.get("current"), 0)
            c["hp_max"] = to_int(bar.get("max"), 0)
            c["conditions"] = [{"name": x.get("name", ""), "rounds": to_int(x.get("rounds"), 0)}
                               for x in data["conditions"]]
            c["sheet_url"] = url_for("characters.detail", character_id=sheet.id)
        else:
            c["character_id"] = None
        c["hp_loaded"] = c.get("hp")

        if not is_master and c["kind"] != "pj":
            c["health"] = health_state(to_int(c.get("hp"), 0), to_int(c.get("hp_max"), 0))
            for secret in ("hp", "hp_max", "hp_loaded", "notes", "sheet_url"):
                c.pop(secret, None)
        out.append(c)

    return {
        "ok": True,
        "name": encounter.name,
        "round_number": encounter.round_number,
        "turn_index": encounter.turn_index,
        "combatants": out,
        "messages": messages or [],
    }


def new_uid():
    return secrets.token_hex(4)


def get_encounter(campaign, encounter_id):
    return Encounter.query.filter_by(id=encounter_id, campaign_id=campaign.id).first_or_404()


@bp.route("/<int:campaign_id>/combate")
@login_required
def encounters(campaign_id):
    campaign = get_campaign(campaign_id)
    is_master = campaign.is_master(current_user)
    items = campaign.encounters.order_by(Encounter.created_at.desc()).all()
    roster = []
    if is_master:
        roster = campaign.characters.order_by(Character.kind, Character.name).all()
    return render_template(
        "campaigns/encounters.html",
        campaign=campaign,
        is_master=is_master,
        encounters=items,
        states={e.id: encounter_state(e, is_master) for e in items},
        roster=roster,
    )


@bp.route("/<int:campaign_id>/combate/novo", methods=["POST"])
@login_required
def encounter_create(campaign_id):
    campaign = get_campaign(campaign_id, master_only=True)
    encounter = Encounter(
        campaign_id=campaign.id,
        name=(request.form.get("name") or "").strip() or "Novo combate",
        combatants=[],
    )
    db.session.add(encounter)
    db.session.commit()
    return redirect(url_for("campaigns.encounters", campaign_id=campaign.id) + "#e%d" % encounter.id)


@bp.route("/<int:campaign_id>/combate/<int:encounter_id>/estado")
@login_required
def encounter_poll(campaign_id, encounter_id):
    campaign = get_campaign(campaign_id)
    encounter = get_encounter(campaign, encounter_id)
    return jsonify(encounter_state(encounter, campaign.is_master(current_user)))


@bp.route("/<int:campaign_id>/combate/<int:encounter_id>/adicionar", methods=["POST"])
@login_required
def encounter_add(campaign_id, encounter_id):
    """Coloca fichas no combate.

    PJs e NPCs entram ligados à ficha (o PV é o da ficha). Criaturas do
    bestiário entram como cópias independentes — "Ghoul 1", "Ghoul 2" — cada
    uma com o próprio PV, sem mexer na ficha modelo.
    """
    campaign = get_campaign(campaign_id, master_only=True)
    encounter = get_encounter(campaign, encounter_id)
    payload = request.get_json(silent=True) or {}
    combatants = copy.deepcopy(encounter.combatants or [])
    linked = {c.get("character_id") for c in combatants if c.get("character_id")}
    key = hp_bar_key(campaign.system)
    added = 0

    if payload.get("party"):
        chosen = campaign.characters.filter_by(kind="pj").all()
    else:
        character = Character.query.filter_by(
            id=to_int(payload.get("character_id")), campaign_id=campaign.id).first_or_404()
        chosen = [character]

    for character in chosen:
        data, _ = sheet_helper.apply_formulas(campaign.system, character.data)
        bar = data["bars"].get(key) or {}
        hp_max = to_int(bar.get("max"), 0)

        if character.kind == "criatura":
            quantity = max(1, min(MAX_SPAWN, to_int(payload.get("quantity"), 1)))
            existing = len([c for c in combatants if c.get("source_id") == character.id])
            for n in range(quantity):
                combatants.append({
                    "uid": new_uid(), "name": "%s %d" % (character.name, existing + n + 1),
                    "init": 0, "hp": hp_max, "hp_max": hp_max, "notes": "",
                    "is_npc": True, "kind": "criatura", "character_id": None,
                    "source_id": character.id,
                })
                added += 1
        elif character.id not in linked:
            combatants.append({
                "uid": new_uid(), "name": character.name, "init": 0,
                "hp": to_int(bar.get("current"), hp_max), "hp_max": hp_max, "notes": "",
                "is_npc": character.kind != "pj", "kind": character.kind,
                "character_id": character.id,
            })
            linked.add(character.id)
            added += 1

    encounter.combatants = combatants
    db.session.commit()
    messages = [] if added else ["Todos já estavam no combate."]
    return jsonify(encounter_state(encounter, True, messages))


@bp.route("/<int:campaign_id>/combate/<int:encounter_id>/salvar", methods=["POST"])
@login_required
def encounter_save(campaign_id, encounter_id):
    campaign = get_campaign(campaign_id, master_only=True)
    encounter = get_encounter(campaign, encounter_id)
    payload = request.get_json(silent=True) or {}
    key = hp_bar_key(campaign.system)

    valid_sheets = {ch.id: ch for ch in campaign.characters.all()}
    messages = []
    combatants = []
    for item in payload.get("combatants") or []:
        name = (item.get("name") or "").strip()
        character_id = to_int(item.get("character_id"), 0) or None
        if character_id not in valid_sheets:
            character_id = None
        if not name and not character_id:
            continue
        combatants.append({
            "uid": (str(item.get("uid") or "")[:16]) or new_uid(),
            "name": (name or valid_sheets[character_id].name)[:80],
            "init": to_int(item.get("init"), 0),
            "hp": to_int(item.get("hp"), 0),
            "hp_max": to_int(item.get("hp_max"), 0),
            "notes": (item.get("notes") or "")[:160],
            "is_npc": bool(item.get("is_npc")),
            "kind": item.get("kind") if item.get("kind") in ("pj", "npc", "criatura") else "criatura",
            "character_id": character_id,
            "source_id": to_int(item.get("source_id"), 0) or None,
            "_hp_loaded": item.get("hp_loaded"),
        })

    # PV mudou no rastreador? Vai para a ficha. Só se o mestre mexeu mesmo
    # (hp diferente do que foi carregado): assim um rastreador aberto há tempo
    # não desfaz o dano que o jogador anotou na própria ficha.
    touched = set()
    for c in combatants:
        loaded = c.pop("_hp_loaded")
        sheet = valid_sheets.get(c["character_id"])
        if sheet is None or key is None or loaded is None or to_int(loaded, c["hp"]) == c["hp"]:
            continue
        data, _ = sheet_helper.apply_formulas(campaign.system, sheet.data)
        bar = dict(data["bars"].get(key) or {})
        maximum = to_int(bar.get("max"), 0)
        bar["current"] = max(-999, min(c["hp"], maximum))
        data["bars"][key] = bar
        sheet.data = data
        sheet._revision_reason = "combate"
        touched.add(sheet.id)

    # Rodada nova: condições com duração perdem uma rodada; as que chegam a
    # zero acabam. Duração 0 significa "sem prazo" e não é tocada.
    new_round = max(1, to_int(payload.get("round_number"), 1))
    if new_round > (encounter.round_number or 1):
        steps = new_round - (encounter.round_number or 1)
        for sheet_id in {c["character_id"] for c in combatants if c["character_id"]}:
            sheet = valid_sheets[sheet_id]
            data = sheet_helper.normalize(copy.deepcopy(sheet.data))
            kept, changed = [], False
            for condition in data["conditions"]:
                rounds = to_int(condition.get("rounds"), 0)
                if rounds <= 0:
                    kept.append(condition)
                    continue
                changed = True
                rounds -= steps
                if rounds <= 0:
                    messages.append("%s: %s acabou." % (sheet.name, condition.get("name")))
                else:
                    condition = dict(condition, rounds=rounds)
                    kept.append(condition)
            if changed:
                data["conditions"] = kept
                sheet.data = data
                sheet._revision_reason = "combate"
                touched.add(sheet.id)

    for sheet_id in touched:
        valid_sheets[sheet_id].bump_version()

    # Ordena por iniciativa sem perder de quem é a vez.
    turn = max(0, to_int(payload.get("turn_index"), 0))
    active_uid = combatants[turn % len(combatants)]["uid"] if combatants else None
    combatants.sort(key=lambda c: c["init"], reverse=True)
    encounter.combatants = combatants
    encounter.round_number = new_round
    encounter.turn_index = next(
        (i for i, c in enumerate(combatants) if c["uid"] == active_uid), 0)
    if "name" in payload:
        encounter.name = (payload.get("name") or encounter.name).strip()[:160]
    db.session.commit()
    return jsonify(encounter_state(encounter, True, messages))


@bp.route("/<int:campaign_id>/combate/<int:encounter_id>/excluir", methods=["POST"])
@login_required
def encounter_delete(campaign_id, encounter_id):
    campaign = get_campaign(campaign_id, master_only=True)
    encounter = get_encounter(campaign, encounter_id)
    db.session.delete(encounter)
    db.session.commit()
    flash("Combate removido.", "success")
    return redirect(url_for("campaigns.encounters", campaign_id=campaign.id))


# --------------------------------------------------------------- rolagens da mesa
@bp.route("/<int:campaign_id>/rolagens")
@login_required
def roll_feed(campaign_id):
    """Rolagens novas desde a última que a tela já mostrou."""
    campaign = get_campaign(campaign_id)
    is_master = campaign.is_master(current_user)
    since = to_int(request.args.get("desde"), 0)

    query = campaign.rolls
    if not is_master:
        query = query.filter(or_(RollLog.secret.is_(False), RollLog.user_id == current_user.id))
    if since:
        rolls = query.filter(RollLog.id > since).order_by(RollLog.id.asc()).limit(50).all()
    else:
        rolls = list(reversed(query.order_by(RollLog.id.desc()).limit(25).all()))
    return jsonify({
        "ok": True,
        "rolls": [r.as_dict() for r in rolls],
        "last": rolls[-1].id if rolls else since,
    })


@bp.route("/<int:campaign_id>/rolar", methods=["POST"])
@login_required
def roll_free(campaign_id):
    """Rolagem livre (sem ficha), como o mestre rolando para um NPC."""
    campaign = get_campaign(campaign_id)
    payload = request.get_json(silent=True) or {}
    try:
        outcome = dice.roll_formula(str(payload.get("formula") or "")[:40])
    except dice.DiceError as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    log = RollLog(
        campaign_id=campaign.id,
        user_id=current_user.id,
        label=(payload.get("label") or payload.get("formula") or "Rolagem").strip()[:120],
        result=str(outcome["result"]),
        detail=outcome["detail"][:400],
        flag=outcome["flag"],
        secret=bool(payload.get("secret")) and campaign.is_master(current_user),
    )
    db.session.add(log)
    db.session.commit()
    return jsonify({"ok": True, "roll": log.as_dict()})


# --------------------------------------------------------------- linha do tempo
@bp.route("/<int:campaign_id>/linha-do-tempo", methods=["GET", "POST"])
@login_required
def timeline(campaign_id):
    campaign = get_campaign(campaign_id)
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("Dê um título ao acontecimento.", "error")
        else:
            db.session.add(
                TimelineEntry(
                    campaign_id=campaign.id,
                    author_id=current_user.id,
                    label=(request.form.get("label") or "").strip()[:120],
                    title=title[:200],
                    body=(request.form.get("body") or "").strip(),
                )
            )
            db.session.commit()
            flash("Registrado na linha do tempo.", "success")
        return redirect(url_for("campaigns.timeline", campaign_id=campaign.id))

    entries = campaign.timeline.order_by(TimelineEntry.created_at.desc()).all()
    return render_template(
        "campaigns/timeline.html",
        campaign=campaign,
        is_master=campaign.is_master(current_user),
        entries=entries,
    )


@bp.route("/<int:campaign_id>/linha-do-tempo/<int:entry_id>/excluir", methods=["POST"])
@login_required
def timeline_delete(campaign_id, entry_id):
    campaign = get_campaign(campaign_id)
    entry = TimelineEntry.query.filter_by(id=entry_id, campaign_id=campaign.id).first_or_404()
    if entry.author_id != current_user.id and not campaign.is_master(current_user):
        abort(403)
    db.session.delete(entry)
    db.session.commit()
    return redirect(url_for("campaigns.timeline", campaign_id=campaign.id))
