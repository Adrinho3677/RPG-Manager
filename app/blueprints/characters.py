# -*- coding: utf-8 -*-
import copy
import json
from datetime import date

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import current_user, login_required

from app import dice
from app import sheet as sheet_helper
from app.blueprints.uploads import UploadError, asset_from_url, remove_file, save_upload
from app.extensions import db
from app.models import Campaign, Character, CharacterRevision, GameSystem, RollLog
from app.utils import clean_color, local_time, script_json, to_float, to_int, unique_key

bp = Blueprint("characters", __name__, url_prefix="/fichas")

KINDS = [("pj", "Personagem jogador"), ("npc", "NPC"), ("criatura", "Criatura / Ameaça")]

ITEM_CATEGORIES = ["geral", "arma", "proteção", "consumível", "munição", "ferramenta", "tesouro"]

# Listas da ficha que chegam como JSON num campo escondido. Para cada uma,
# quais campos são texto (com tamanho máximo), inteiro, decimal ou booleano.
RECORD_SPECS = {
    "inventory": {
        "limit": 300,
        "text": {"name": 120, "desc": 600, "category": 40},
        "int": ("qty", "value"),
        "float": ("weight",),
        "bool": ("equipped",),
    },
    "abilities": {"limit": 200, "text": {"name": 120, "desc": 1500}},
    "attacks": {
        "limit": 100,
        "text": {"name": 120, "test": 60, "damage": 60, "crit": 40, "range": 60, "desc": 400},
        "int": ("bonus",),
    },
    "spells": {
        "limit": 300,
        "text": {"name": 120, "cost": 40, "execution": 60, "range": 60,
                 "duration": 60, "desc": 1500},
        "int": ("level",),
        "bool": ("prepared",),
    },
    "conditions": {"limit": 50, "text": {"name": 60, "desc": 200}, "int": ("rounds",)},
    "progress": {"limit": 300, "text": {"name": 120, "desc": 400, "at": 20}, "int": ("amount",)},
}


def get_character(character_id, for_edit=False):
    character = db.session.get(Character, character_id) or abort(404)
    if for_edit:
        if not character.editable_by(current_user):
            abort(403)
    elif not character.viewable_by(current_user):
        abort(403)
    return character


def usable_systems():
    return GameSystem.query.filter(
        (GameSystem.is_preset.is_(True)) | (GameSystem.owner_id == current_user.id)
    ).order_by(GameSystem.is_preset.desc(), GameSystem.name).all()


@bp.route("/")
@login_required
def index():
    mine = (
        Character.query.filter_by(owner_id=current_user.id)
        .order_by(Character.updated_at.desc())
        .all()
    )
    return render_template("characters/index.html", characters=mine)


@bp.route("/nova", methods=["GET", "POST"])
@login_required
def create():
    campaign_id = to_int(request.args.get("campanha") or request.form.get("campaign_id"))
    campaign = db.session.get(Campaign, campaign_id) if campaign_id else None
    if campaign and not campaign.can_view(current_user):
        abort(403)

    my_campaigns = [m.campaign for m in current_user.memberships.all() if m.campaign]

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        kind = request.form.get("kind") if request.form.get("kind") in dict(KINDS) else "pj"
        if campaign:
            system = campaign.system
        else:
            system_id = to_int(request.form.get("system_id"))
            system = db.session.get(GameSystem, system_id) if system_id else None

        if not name:
            flash("A ficha precisa de um nome.", "error")
        elif system is None or not system.usable_by(current_user):
            flash("Escolha um sistema válido.", "error")
        elif kind != "pj" and campaign and not campaign.is_master(current_user):
            flash("Apenas o mestre cria NPCs e criaturas.", "error")
        else:
            character = Character(
                name=name,
                kind=kind,
                concept=(request.form.get("concept") or "").strip(),
                avatar_url=(request.form.get("avatar_url") or "").strip(),
                owner_id=current_user.id,
                campaign_id=campaign.id if campaign else None,
                system_id=system.id,
                visible_to_players=(kind == "pj") or bool(request.form.get("visible_to_players")),
                data=sheet_helper.blank_data(system),
            )
            db.session.add(character)
            db.session.commit()
            flash("Ficha criada. Bora preencher!", "success")
            return redirect(url_for("characters.detail", character_id=character.id))

    return render_template(
        "characters/new.html",
        systems=usable_systems(),
        campaign=campaign,
        my_campaigns=my_campaigns,
        kinds=KINDS,
    )


@bp.route("/<int:character_id>", methods=["GET", "POST"])
@login_required
def detail(character_id):
    character = get_character(character_id)
    can_edit = character.editable_by(current_user)

    if request.method == "POST":
        if not can_edit:
            abort(403)
        if request.headers.get("X-Requested-With") == "fetch":
            return autosave(character)
        return full_save(character)

    data = sheet_helper.build(character)
    campaign = character.campaign
    return render_template(
        "characters/sheet.html",
        character=character,
        sheet=data,
        can_edit=can_edit,
        categories=ITEM_CATEGORIES,
        sheet_json=script_json(
            {
                "id": character.id,
                "version": character.version,
                "roll": data["roll"],
                "display": data["display"],
                "skill_mode": data["skill_mode"],
                "load": {k: data["load"][k]
                         for k in ("mode", "unit", "capacity", "attr", "base",
                                   "per_point", "overload")},
                "categories": ITEM_CATEGORIES,
                "skills": [{"key": s["key"], "name": s["name"]} for s in data["skills"]],
                "labels": data["labels"],
                "state_url": url_for("characters.state", character_id=character.id),
                "roll_url": url_for("characters.roll", character_id=character.id),
                "feed_url": (url_for("campaigns.roll_feed", campaign_id=campaign.id)
                             if campaign else None),
                "is_master": bool(campaign and campaign.is_master(current_user)),
            },
        ),
    )


def full_save(character):
    """Envio do formulário inteiro: botão Salvar, descanso, adicionar campo...

    Como manda todos os campos, sobrescreveria qualquer mudança feita por outra
    pessoa desde que esta página abriu. Por isso é recusado se a versão
    enviada estiver velha.
    """
    sent = request.form.get("version")
    if sent is not None and to_int(sent, -1) != character.version:
        flash("Esta ficha foi alterada por outra pessoa enquanto você editava. "
              "Nada foi salvo para não apagar a mudança dela — recarregue a página "
              "e refaça a sua alteração.", "error")
        return redirect(url_for("characters.detail", character_id=character.id))

    apply_form(character, request.form)
    action = request.form.get("__action") or ""
    message = handle_action(character, action, request.form)
    character.bump_version()
    db.session.commit()
    if message:
        flash(message, "success")
    return redirect(url_for("characters.detail", character_id=character.id))


def autosave(character):
    """Salvamento automático: o navegador manda só os campos que mudaram.

    Aplicar só esses campos em cima do que está no banco faz edições em partes
    diferentes da ficha se juntarem — o mestre mexe no PV, o jogador no
    inventário, e as duas coisas ficam. Se a versão enviada estava velha, a
    gravação acontece mesmo assim (não apaga nada de ninguém) e a resposta avisa
    que a tela do jogador está desatualizada.
    """
    sent = to_int(request.form.get("version"), -1)
    stale = sent != character.version
    apply_form(character, request.form)
    character.bump_version()
    db.session.commit()
    return jsonify(state_payload(character, stale=stale))


def state_payload(character, stale=False):
    data = sheet_helper.build(character)
    return {
        "ok": True,
        "version": character.version,
        "stale": stale,
        "bars": {b["key"]: {"current": b["current"], "max": b["max"], "temp": b["temp"],
                            "auto": bool(b["max_formula"]), "error": b["formula_error"]}
                 for b in data["bars"]},
        "conditions": data["conditions"],
        "load": {k: data["load"][k] for k in ("used", "capacity", "percent", "state", "label")},
    }


@bp.route("/<int:character_id>/estado")
@login_required
def state(character_id):
    """Versão atual da ficha, para a tela perceber mudanças de outra pessoa."""
    character = get_character(character_id)
    return jsonify(state_payload(character))


@bp.route("/<int:character_id>/rolar", methods=["POST"])
@login_required
def roll(character_id):
    """Rola no servidor. Numa campanha, a rolagem vai para o registro da mesa."""
    character = get_character(character_id, for_edit=True)
    payload = request.get_json(silent=True) or {}
    label = (payload.get("label") or "Rolagem").strip()[:120]
    sysroll = (character.system.data or {}).get("roll") or {}

    try:
        if payload.get("formula"):
            outcome = dice.roll_formula(str(payload.get("formula"))[:40])
            label = (payload.get("label") or payload.get("formula")).strip()[:120]
        else:
            target = payload.get("target")
            outcome = dice.roll_check(
                sysroll.get("type", "d20_mod"),
                dice=to_int(payload.get("dice"), 1),
                bonus=to_int(payload.get("bonus"), 0),
                target=to_int(target, 0) if target is not None else None,
                success_on=to_int(sysroll.get("success_on"), 6),
            )
    except dice.DiceError as error:
        return jsonify({"ok": False, "message": str(error)}), 400

    entry = {
        "label": label,
        "result": str(outcome["result"]),
        "detail": outcome["detail"],
        "flag": outcome["flag"],
        "secret": bool(payload.get("secret")),
        "who": character.name,
    }
    if character.campaign_id:
        log = RollLog(
            campaign_id=character.campaign_id,
            user_id=current_user.id,
            character_id=character.id,
            label=label,
            result=entry["result"],
            detail=outcome["detail"][:400],
            flag=outcome["flag"],
            secret=entry["secret"],
        )
        db.session.add(log)
        db.session.commit()
        entry = log.as_dict()
    return jsonify({"ok": True, "roll": entry})


@bp.route("/<int:character_id>/historico")
@login_required
def history(character_id):
    character = get_character(character_id, for_edit=True)
    return render_template(
        "characters/history.html",
        character=character,
        revisions=character.revisions.limit(60).all(),
    )


def restore(character, revision):
    """Volta a ficha para o estado guardado. Também vira uma revisão — dá para desfazer."""
    character.data = copy.deepcopy(revision.data)
    character._revision_reason = "restauração"
    character.bump_version()
    db.session.commit()


@bp.route("/<int:character_id>/historico/<int:revision_id>/restaurar", methods=["POST"])
@login_required
def history_restore(character_id, revision_id):
    character = get_character(character_id, for_edit=True)
    revision = CharacterRevision.query.filter_by(
        id=revision_id, character_id=character.id).first_or_404()
    when = local_time(revision.created_at)
    restore(character, revision)
    flash("Ficha restaurada para como estava em %s. Se foi engano, dá para desfazer." % when,
          "success")
    return redirect(url_for("characters.detail", character_id=character.id))


@bp.route("/<int:character_id>/desfazer", methods=["POST"])
@login_required
def undo(character_id):
    character = get_character(character_id, for_edit=True)
    revision = character.revisions.first()
    if revision is None:
        flash("Não há nada para desfazer.", "warning")
    else:
        changed = ", ".join(revision.changed_list) or "a ficha"
        restore(character, revision)
        flash("Desfeito: %s voltou ao que era antes." % changed, "success")
    return redirect(url_for("characters.detail", character_id=character.id))


@bp.route("/<int:character_id>/imprimir")
@login_required
def print_sheet(character_id):
    """Versão em papel: o navegador gera o PDF por "Imprimir → Salvar como PDF"."""
    character = get_character(character_id)
    return render_template(
        "characters/print.html",
        character=character,
        sheet=sheet_helper.build(character),
        is_master=bool(character.campaign and character.campaign.is_master(current_user)),
    )


@bp.route("/<int:character_id>/identidade", methods=["POST"])
@login_required
def identity(character_id):
    character = get_character(character_id, for_edit=True)
    character.name = (request.form.get("name") or character.name).strip()
    character.concept = (request.form.get("concept") or "").strip()
    kind = request.form.get("kind")
    if kind in dict(KINDS):
        character.kind = kind
    character.visible_to_players = bool(request.form.get("visible_to_players"))

    campaign_id = to_int(request.form.get("campaign_id"))
    if campaign_id:
        campaign = db.session.get(Campaign, campaign_id)
        if campaign and campaign.can_view(current_user) and campaign.system_id == character.system_id:
            character.campaign_id = campaign.id
    elif request.form.get("campaign_id") == "":
        character.campaign_id = None

    old_asset = asset_from_url(character.avatar_url)
    upload = request.files.get("avatar_file")
    if upload is not None and upload.filename:
        try:
            asset = save_upload(upload, "avatar", current_user, character.campaign)
            db.session.flush()
            character.avatar_url = asset.url
        except UploadError as error:
            db.session.rollback()
            flash(str(error), "error")
            return redirect(url_for("characters.detail", character_id=character.id))
    elif request.form.get("remove_avatar"):
        character.avatar_url = ""
    else:
        character.avatar_url = (request.form.get("avatar_url") or character.avatar_url or "").strip()

    # Apaga o retrato anterior se ele era um arquivo nosso e foi trocado.
    if old_asset and character.avatar_url != old_asset.url and old_asset.owner_id == current_user.id:
        remove_file(old_asset)
        db.session.delete(old_asset)

    character.bump_version()
    db.session.commit()
    flash("Identidade atualizada.", "success")
    return redirect(url_for("characters.detail", character_id=character.id))


@bp.route("/<int:character_id>/duplicar", methods=["POST"])
@login_required
def duplicate(character_id):
    character = get_character(character_id)
    clone = Character(
        name="%s (cópia)" % character.name,
        kind=character.kind,
        concept=character.concept,
        avatar_url=character.avatar_url,
        owner_id=current_user.id,
        campaign_id=character.campaign_id,
        system_id=character.system_id,
        visible_to_players=character.visible_to_players,
        data=copy.deepcopy(character.data or {}),
    )
    db.session.add(clone)
    db.session.commit()
    return redirect(url_for("characters.detail", character_id=clone.id))


@bp.route("/<int:character_id>/excluir", methods=["POST"])
@login_required
def delete(character_id):
    character = get_character(character_id, for_edit=True)
    campaign_id = character.campaign_id
    # O SQLite ignora ON DELETE SET NULL sem PRAGMA; o MySQL recusaria apagar.
    # Soltar as rolagens à mão funciona igual nos dois.
    RollLog.query.filter_by(character_id=character.id).update({"character_id": None})
    db.session.delete(character)
    db.session.commit()
    flash("Ficha excluída.", "success")
    if campaign_id:
        return redirect(url_for("campaigns.overview", campaign_id=campaign_id))
    return redirect(url_for("characters.index"))


# ------------------------------------------------------------------ helpers
def parse_records(block, raw):
    """Valida uma lista de registros vinda do campo escondido em JSON."""
    spec = RECORD_SPECS[block]
    try:
        items = json.loads(raw or "[]")
    except ValueError:
        return []
    if not isinstance(items, list):
        return []

    clean = []
    for item in items[: spec["limit"]]:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        if not name:
            continue
        record = {}
        for field, size in spec["text"].items():
            record[field] = str(item.get(field) or "").strip()[:size]
        record["name"] = name[: spec["text"]["name"]]
        for field in spec.get("int", ()):
            record[field] = to_int(item.get(field), 0)
        for field in spec.get("float", ()):
            record[field] = round(max(0.0, to_float(item.get(field), 0)), 3)
        for field in spec.get("bool", ()):
            record[field] = bool(item.get(field))
        if block == "inventory":
            record["qty"] = max(0, record.get("qty", 1))
            if record.get("category") not in ITEM_CATEGORIES:
                record["category"] = "geral"
        clean.append(record)
    return clean


def apply_form(character, form):
    """Grava no personagem os campos presentes no formulário.

    Campos ausentes ficam como estão no banco — é o que permite ao salvamento
    automático mandar só o que mudou.
    """
    data = sheet_helper.normalize(copy.deepcopy(character.data))
    defs = sheet_helper.merged_defs(character.system, data)

    for attribute in defs["attributes"]:
        field = "attr__%s" % attribute["key"]
        if field in form:
            value = to_int(form.get(field), to_int(attribute.get("default", 0)))
            low = to_int(attribute.get("min", -99), -99)
            high = to_int(attribute.get("max", 99), 99)
            data["attributes"][attribute["key"]] = max(low, min(high, value))

    for bar in defs["bars"]:
        key = bar["key"]
        prefix = "bar__%s__" % key
        if not any((prefix + part) in form for part in ("max", "current", "temp")):
            continue
        stored = dict(data["bars"].get(key) or {})
        old_max = to_int(stored.get("max", bar.get("default_max", 10)), 10)
        maximum = to_int(form.get(prefix + "max"), old_max) if (prefix + "max") in form else old_max
        maximum = max(0, maximum)
        old_current = to_int(stored.get("current", maximum), maximum)
        current = (to_int(form.get(prefix + "current"), old_current)
                   if (prefix + "current") in form else old_current)
        temp = (to_int(form.get(prefix + "temp"), 0)
                if (prefix + "temp") in form else to_int(stored.get("temp", 0)))
        stored["max"] = maximum
        stored["current"] = max(-999, min(current, maximum))
        stored["temp"] = temp
        data["bars"][key] = stored

    for skill in defs["skills"]:
        key = skill["key"]
        prefix = "skill__%s__" % key
        parts = ("value", "train", "prof", "other")
        if not any((prefix + part) in form for part in parts):
            continue
        stored = dict(data["skills"].get(key) or {})
        defaults = {"value": to_int(skill.get("default", 0)), "train": 0, "prof": 0, "other": 0}
        for part in parts:
            previous = to_int(stored.get(part, defaults[part]), defaults[part])
            stored[part] = (to_int(form.get(prefix + part), previous)
                            if (prefix + part) in form else previous)
        data["skills"][key] = stored

    for field in defs["meta_fields"]:
        name = "meta__%s" % field["key"]
        if name in form:
            data["meta"][field["key"]] = (form.get(name) or "").strip()[:400]

    for block in RECORD_SPECS:
        if block in form:
            data[block] = parse_records(block, form.get(block))

    for coin in (character.system.data or {}).get("currencies") or []:
        field = "money__%s" % coin["key"]
        if field in form:
            data["money"][coin["key"]] = max(0, to_int(form.get(field), 0))

    if "xp" in form:
        data["xp"] = max(0, to_int(form.get("xp"), 0))

    for text_field in ("notes", "history", "appearance"):
        if text_field in form:
            data[text_field] = (form.get(text_field) or "").strip()[:20000]

    # Atributo ou NEX mudou? O máximo das barras com fórmula acompanha.
    data, _ = sheet_helper.apply_formulas(character.system, data)
    character.data = data


def handle_action(character, action, form):
    """Adiciona ou remove campos criados dentro da própria ficha."""
    if not action:
        return None

    data = sheet_helper.normalize(copy.deepcopy(character.data))
    custom = data["custom"]
    defs = sheet_helper.merged_defs(character.system, data)

    if action == "add_attribute":
        name = (form.get("new_attr_name") or "").strip()
        if not name:
            return None
        used = {a["key"] for a in defs["attributes"]}
        key = unique_key(name, used)
        custom["attributes"].append(
            {
                "key": key,
                "name": name[:60],
                "abbr": (form.get("new_attr_abbr") or name[:3]).strip()[:6].upper(),
                "default": to_int(form.get("new_attr_value"), 0),
                "min": to_int(form.get("new_attr_min"), 0),
                "max": to_int(form.get("new_attr_max"), 10),
            }
        )
        data["attributes"][key] = to_int(form.get("new_attr_value"), 0)
        character.data = data
        return "Atributo “%s” adicionado à ficha." % name

    if action == "add_bar":
        name = (form.get("new_bar_name") or "").strip()
        if not name:
            return None
        used = {b["key"] for b in defs["bars"]}
        key = unique_key(name, used)
        maximum = to_int(form.get("new_bar_max"), 10)
        custom["bars"].append(
            {
                "key": key,
                "name": name[:60],
                "abbr": (form.get("new_bar_abbr") or name[:3]).strip()[:6].upper(),
                "color": clean_color(form.get("new_bar_color")),
                "default_max": maximum,
                "formula": (form.get("new_bar_formula") or "").strip()[:120],
                "max_formula": (form.get("new_bar_max_formula") or "").strip()[:160],
            }
        )
        data["bars"][key] = {"current": maximum, "max": maximum, "temp": 0}
        data, errors = sheet_helper.apply_formulas(character.system, data)
        if key in data["bars"] and not errors.get(key) and custom["bars"][-1]["max_formula"]:
            data["bars"][key]["current"] = data["bars"][key]["max"]
        character.data = data
        if errors.get(key):
            return "Barra “%s” adicionada, mas a fórmula não funcionou: %s" % (name, errors[key])
        return "Barra “%s” adicionada à ficha." % name

    if action == "add_skill":
        name = (form.get("new_skill_name") or "").strip()
        if not name:
            return None
        used = {s["key"] for s in defs["skills"]}
        key = unique_key(name, used)
        attr = form.get("new_skill_attr") or ""
        if attr not in {a["key"] for a in defs["attributes"]}:
            attr = defs["attributes"][0]["key"] if defs["attributes"] else ""
        custom["skills"].append(
            {"key": key, "name": name[:60], "attr": attr,
             "default": to_int(form.get("new_skill_default"), 0)}
        )
        data["skills"][key] = {
            "value": to_int(form.get("new_skill_default"), 0),
            "train": 0,
            "prof": 0,
            "other": 0,
        }
        character.data = data
        return "Perícia “%s” adicionada à ficha." % name

    if action == "add_meta":
        name = (form.get("new_meta_name") or "").strip()
        if not name:
            return None
        used = {m["key"] for m in defs["meta_fields"]}
        key = unique_key(name, used)
        ftype = form.get("new_meta_type")
        custom["meta_fields"].append(
            {
                "key": key,
                "name": name[:60],
                "type": ftype if ftype in ("text", "number", "textarea") else "text",
            }
        )
        data["meta"][key] = ""
        character.data = data
        return "Campo “%s” adicionado à ficha." % name

    if action in ("rest:short", "rest:long"):
        kind = action.split(":")[1]
        rested, changes = sheet_helper.apply_rest(character.system, data, kind)
        character.data = rested
        character._revision_reason = "descanso"
        nome = "Descanso curto" if kind == "short" else "Descanso longo"
        if not changes:
            return "%s: nada mudou (tudo já estava no máximo)." % nome
        return "%s — %s." % (nome, "; ".join(changes))

    if action == "add_xp":
        amount = to_int(form.get("new_xp_amount"), 0)
        note = (form.get("new_xp_note") or "").strip()
        if not amount and not note:
            return None
        data["xp"] = max(0, to_int(data.get("xp"), 0) + amount)
        data["progress"].append(
            {
                "name": note[:120] or ("%+d de experiência" % amount),
                "amount": amount,
                "desc": "",
                "at": date.today().isoformat(),
            }
        )
        character.data = data
        return "Registrado: %+d de experiência (total %d)." % (amount, data["xp"])

    if action.startswith("remove:"):
        parts = action.split(":", 2)
        group = parts[1] if len(parts) > 2 else ""
        key = parts[2] if len(parts) > 2 else ""
        mapping = {
            "attribute": ("attributes", "attributes"),
            "bar": ("bars", "bars"),
            "skill": ("skills", "skills"),
            "meta": ("meta_fields", "meta"),
        }
        if group in mapping and key:
            def_bucket, value_bucket = mapping[group]
            custom[def_bucket] = [i for i in custom[def_bucket] if i.get("key") != key]
            data[value_bucket].pop(key, None)
            character.data = data
            return "Campo removido da ficha."

    return None
