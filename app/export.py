# -*- coding: utf-8 -*-
"""Exporta uma campanha inteira num ZIP: o backup do mestre.

Dentro:
    campanha.json   tudo em JSON legível (fichas, sessões, anotações, combates…)
    imagens/        mapas da campanha e retratos enviados das fichas
    LEIA-ME.txt     o que é cada coisa

Privacidade: só o mestre exporta, e por isso as anotações secretas e os roteiros
vão junto — é o caderno dele. E-mails dos jogadores NÃO entram; só os nomes de
usuário.
"""
import json
import os
import tempfile
import zipfile
from datetime import datetime

from flask import current_app

from app.models import Asset, Character, Encounter, GameSession, Note, RollLog, TimelineEntry
from app.utils import local_time

FORMAT = "grimorio-campanha"
MAX_ROLLS = 1000

README = """Exportação do Grimório
=====================

campanha.json  - a campanha inteira em JSON (abre em qualquer editor de texto)
imagens/       - mapas da campanha e retratos enviados das fichas

Horários no campo "..._utc" estão em UTC; os campos "..._local" já estão no
fuso configurado do site.

Este arquivo contém as anotações secretas e os roteiros do mestre. Guarde com
cuidado e não compartilhe com os jogadores.
"""


def _stamp(value):
    if value is None:
        return None
    return {"utc": value.isoformat() + "Z", "local": local_time(value)}


def _asset_file(asset, used):
    """Nome dentro do ZIP; None se o arquivo sumiu do disco."""
    path = os.path.join(current_app.config["UPLOAD_DIR"], asset.filename)
    if not os.path.exists(path):
        return None
    name = "imagens/" + asset.filename
    used[name] = path
    return name


def build_document(campaign):
    """Monta o dicionário da exportação e a lista de imagens a incluir."""
    from app.blueprints.uploads import asset_from_url

    images = {}
    system = campaign.system

    characters = []
    for ch in campaign.characters.order_by(Character.kind, Character.name).all():
        avatar = asset_from_url(ch.avatar_url)
        characters.append({
            "nome": ch.name,
            "tipo": ch.kind,
            "conceito": ch.concept,
            "dono": ch.owner.username,
            "visivel_para_jogadores": bool(ch.visible_to_players),
            "retrato": (_asset_file(avatar, images) if avatar else ch.avatar_url) or None,
            "versao": ch.version,
            "atualizada": _stamp(ch.updated_at),
            "dados": ch.data or {},
        })

    sessions = []
    for item in campaign.sessions.order_by(GameSession.number).all():
        sessions.append({
            "numero": item.number,
            "titulo": item.title,
            "data": item.scheduled_for.isoformat() if item.scheduled_for else None,
            "horario": item.start_time,
            "situacao": item.status,
            "sinopse": item.synopsis,
            "roteiro_do_mestre": item.plan,
            "resumo": item.recap,
            "cenas": item.beats or [],
            "presencas": [{"jogador": a.user.username, "resposta": a.label, "recado": a.comment}
                          for a in item.attendance.all()],
        })

    notes = []
    for note in campaign.notes.order_by(Note.created_at).all():
        notes.append({
            "titulo": note.title,
            "texto": note.body,
            "categoria": note.category,
            "tags": note.tag_list,
            "visibilidade": note.visibility,
            "para": sorted(r.user.username for r in note.recipients),
            "fixada": bool(note.pinned),
            "autor": note.author.username,
            "revelada": _stamp(note.revealed_at),
            "atualizada": _stamp(note.updated_at),
        })

    maps = []
    for asset in campaign.assets.filter(Asset.kind == "mapa").order_by(Asset.created_at).all():
        maps.append({
            "titulo": asset.title,
            "arquivo": _asset_file(asset, images),
            "visibilidade": asset.visibility,
            "enviado_por": asset.owner.username,
            "enviado": _stamp(asset.created_at),
        })

    rolls = campaign.rolls.order_by(RollLog.id.desc()).limit(MAX_ROLLS).all()

    document = {
        "formato": FORMAT,
        "versao": 1,
        "exportado": _stamp(datetime.utcnow()),
        "campanha": {
            "nome": campaign.name,
            "subtitulo": campaign.tagline,
            "descricao": campaign.description,
            "situacao": campaign.status,
            "mestre": campaign.master.username,
            "criada": _stamp(campaign.created_at),
        },
        "sistema": {"nome": system.name, "descricao": system.description, "dados": system.data or {}},
        "mesa": [{"usuario": m.user.username, "papel": m.role, "entrou": _stamp(m.joined_at)}
                 for m in campaign.members.all() if m.user],
        "fichas": characters,
        "sessoes": sessions,
        "anotacoes": notes,
        "combates": [{"nome": e.name, "rodada": e.round_number, "combatentes": e.combatants or []}
                     for e in campaign.encounters.order_by(Encounter.created_at).all()],
        "linha_do_tempo": [{"quando_no_jogo": t.label, "titulo": t.title, "texto": t.body,
                            "autor": t.author.username, "registrado": _stamp(t.created_at)}
                           for t in campaign.timeline.order_by(TimelineEntry.created_at).all()],
        "mapas": maps,
        "rolagens": [dict(r.as_dict(), quando=_stamp(r.created_at)) for r in reversed(rolls)],
    }
    return document, images


def build_zip(campaign):
    """Grava o ZIP num arquivo temporário e devolve o arquivo aberto, no início.

    SpooledTemporaryFile fica em memória até 8 MB e passa para o disco depois:
    uma campanha com muitos mapas não estoura a memória do PythonAnywhere.
    """
    document, images = build_document(campaign)
    buffer = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("campanha.json", json.dumps(document, ensure_ascii=False, indent=2))
        archive.writestr("LEIA-ME.txt", README)
        for name, path in images.items():
            archive.write(path, name)
    buffer.seek(0)
    return buffer
