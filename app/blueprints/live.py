# -*- coding: utf-8 -*-
"""Uma consulta só para tudo que atualiza sozinho na tela.

Antes a tela de combate perguntava ao servidor por três caminhos (rastreador,
mapa e rolagens), cada um no seu ritmo. No plano gratuito do PythonAnywhere,
que limita processamento, cada requisição conta. Agora a página pergunta uma
vez só, dizendo o que está mostrando e o que já tem:

    GET /campanhas/<id>/ao-vivo?s=rolls:0:12,enc:3:ab12cd,board:3:,clocks::ef01

Cada item é nome:argumento:marca. A marca é o que a tela já tem (o id da última
rolagem, ou o resumo do último estado). Se nada mudou a seção volta como
{"same": true} e o navegador não redesenha nada.
"""
import hashlib
import json

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from app.models import Character
from app.utils import to_int

bp = Blueprint("live", __name__, url_prefix="/campanhas")

MAX_SECTIONS = 12


def digest(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _versioned(value, token):
    mark = digest(value)
    if mark == token:
        return {"same": True}
    return {"mark": mark, "data": value}


# ------------------------------------------------------------------ seções
def section_rolls(campaign, is_master, arg, token):
    from app.blueprints.campaigns import recent_rolls
    result = recent_rolls(campaign, is_master, to_int(token, 0))
    if token and not result["rolls"]:
        return {"same": True}
    return {"mark": str(result["last"]), "data": result["rolls"]}


def section_encounter(campaign, is_master, arg, token):
    from app.blueprints.campaigns import encounter_state, get_encounter
    encounter = get_encounter(campaign, to_int(arg, 0))
    return _versioned(encounter_state(encounter, is_master), token)


def section_board(campaign, is_master, arg, token):
    from app.blueprints.campaigns import board_payload, get_encounter
    encounter = get_encounter(campaign, to_int(arg, 0))
    return _versioned(board_payload(campaign, encounter), token)


def section_sheet(campaign, is_master, arg, token):
    """Só a versão da ficha: a própria ficha decide se precisa recarregar."""
    sheet = Character.query.filter_by(id=to_int(arg, 0), campaign_id=campaign.id).first()
    if sheet is None or not (is_master or sheet.owner_id == current_user.id
                             or sheet.visible_to_players):
        abort(404)
    if token == str(sheet.version):
        return {"same": True}
    return {"mark": str(sheet.version), "data": {"version": sheet.version}}


def section_clocks(campaign, is_master, arg, token):
    from app.blueprints.table import clocks_payload
    return _versioned(clocks_payload(campaign, is_master), token)


def section_spotlight(campaign, is_master, arg, token):
    from app.blueprints.table import spotlight_payload
    data = spotlight_payload(campaign)
    if data is None or str(data["seq"]) == token:
        return {"same": True}
    return {"mark": str(data["seq"]), "data": data}


def section_treasure(campaign, is_master, arg, token):
    from app.blueprints.table import treasure_payload
    return _versioned(treasure_payload(campaign), token)


SECTIONS = {
    "rolls": section_rolls,
    "enc": section_encounter,
    "board": section_board,
    "sheet": section_sheet,
    "clocks": section_clocks,
    "spot": section_spotlight,
    "treasure": section_treasure,
}


@bp.route("/<int:campaign_id>/ao-vivo")
@login_required
def live(campaign_id):
    from app.blueprints.campaigns import get_campaign
    campaign = get_campaign(campaign_id)
    is_master = campaign.is_master(current_user)
    out = {}
    specs = [item for item in (request.args.get("s") or "").split(",") if item][:MAX_SECTIONS]
    for spec in specs:
        name, _, rest = spec.partition(":")
        arg, _, token = rest.partition(":")
        handler = SECTIONS.get(name)
        if handler is None:
            continue
        out["%s:%s" % (name, arg)] = handler(campaign, is_master, arg[:20], token[:40])
    return jsonify({"ok": True, "sections": out})
