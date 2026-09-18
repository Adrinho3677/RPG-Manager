# -*- coding: utf-8 -*-
"""Histórico das fichas.

Um único ponto captura tudo: antes de cada gravação no banco, se o JSON de uma
ficha mudou, o estado anterior vira uma CharacterRevision. Assim entram no
histórico as edições da própria ficha, o dano dado pelo rastreador de combate,
o XP distribuído na sessão, o descanso — sem cada rota precisar lembrar.

O salvamento automático grava a cada pausa na digitação. Para o histórico não
virar uma revisão por segundo, alterações seguidas da mesma pessoa dentro de
alguns minutos se juntam numa revisão só (a que guarda o estado de antes da
primeira delas).
"""
from datetime import datetime, timedelta

from flask import has_request_context
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

GROUP_WINDOW = timedelta(minutes=5)
KEEP = 60

SECTION_LABELS = {
    "attributes": "atributos",
    "bars": "barras",
    "skills": "perícias",
    "meta": "identidade",
    "money": "dinheiro",
    "custom": "campos extras",
    "inventory": "inventário",
    "abilities": "habilidades",
    "attacks": "ataques",
    "spells": "magias",
    "conditions": "condições",
    "progress": "evolução",
    "xp": "experiência",
    "notes": "notas",
    "history": "história",
    "appearance": "aparência",
}


def changed_sections(old, new):
    old, new = old or {}, new or {}
    keys = set(old) | set(new)
    return sorted({SECTION_LABELS.get(k, k) for k in keys if old.get(k) != new.get(k)})


def _current_user_id():
    if not has_request_context():
        return None
    from flask_login import current_user
    return current_user.id if getattr(current_user, "is_authenticated", False) else None


def _before_flush(session, flush_context, instances):
    from app.models import Character, CharacterRevision

    for obj in list(session.dirty):
        if not isinstance(obj, Character):
            continue
        state = inspect(obj)
        history = state.attrs.data.history
        if not history.has_changes() or not history.deleted:
            continue
        old = history.deleted[0]
        new = obj.data
        sections = changed_sections(old, new)
        if not sections:
            continue

        version_history = state.attrs.version.history
        old_version = (version_history.deleted[0] if version_history.deleted
                       else obj.version) or 1
        author_id = _current_user_id()
        reason = getattr(obj, "_revision_reason", None) or "edição"
        now = datetime.utcnow()

        with session.no_autoflush:
            last = (session.query(CharacterRevision)
                    .filter_by(character_id=obj.id)
                    .order_by(CharacterRevision.id.desc())
                    .first())
            same_burst = (
                last is not None
                and last.author_id == author_id
                and last.reason == reason
                and reason == "edição"
                and now - (last.updated_at or last.created_at) < GROUP_WINDOW
            )
            if same_burst:
                # Continua a mesma leva: o estado "de antes" já está guardado;
                # só acumula o que mudou.
                last.changed = ",".join(sorted(set(last.changed_list) | set(sections)))[:300]
                last.updated_at = now
                continue

            session.add(CharacterRevision(
                character_id=obj.id,
                author_id=author_id,
                version=old_version,
                data=old,
                changed=",".join(sections)[:300],
                reason=reason[:40],
                created_at=now,
                updated_at=now,
            ))

            # Guarda só as mais recentes.
            stale = (session.query(CharacterRevision.id)
                     .filter_by(character_id=obj.id)
                     .order_by(CharacterRevision.id.desc())
                     .offset(KEEP - 1)
                     .all())
            if stale:
                session.query(CharacterRevision).filter(
                    CharacterRevision.id.in_([row.id for row in stale])
                ).delete(synchronize_session=False)


_registered = False


def register():
    global _registered
    if not _registered:
        event.listen(Session, "before_flush", _before_flush)
        _registered = True
