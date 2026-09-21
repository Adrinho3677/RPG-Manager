# -*- coding: utf-8 -*-
"""Importa um ZIP gerado por "Exportar campanha" (app/export.py) como uma
campanha nova, com quem importou de mestre.

O que volta: sistema (reaproveita um igual que já exista), fichas, retratos,
sessões, anotações, mapas, combates (com mapa tático), linha do tempo,
relógios, tesouro e calendário. O que não volta: a mesa (as pessoas são
convidadas de novo), presenças e rolagens — dependem de contas que talvez nem
existam neste site.

Fichas ficam com quem importou, marcadas com o nome do dono original; o mestre
entrega cada uma a alguém da mesa na tela "Mesa". Entregar sozinho, pelo nome
de usuário, seria perigoso: qualquer um pode criar uma conta com o nome "ana".

Tudo ou nada: se algo falhar no meio, nenhuma linha é gravada e as imagens já
copiadas são apagadas.
"""
import io
import json
import os
import secrets
import zipfile
from datetime import date

from flask import current_app

from app import board as board_helper
from app import sheet as sheet_helper
from app import treasure as treasure_helper
from app import worldcal
from app.export import FORMAT
from app.extensions import db
from app.models import (Asset, Campaign, CampaignMember, Character, Clock, Encounter,
                        GameSession, GameSystem, Note, TimelineEntry)
from app.utils import slugify, to_int

MAX_MEMBERS = 800
MAX_TOTAL_BYTES = 80 * 1024 * 1024
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_RATIO = 200  # compressão acima disso é "bomba de zip"


class ImportError_(ValueError):
    """Arquivo inválido: a mensagem vai para a pessoa."""


def _minute(value):
    return value if isinstance(value, int) and 0 <= value < 24 * 60 else None


def _text(value, limit):
    return str(value or "").strip()[:limit]


class _Importer(object):
    def __init__(self, archive, user):
        self.archive = archive
        self.user = user
        self.written = []   # arquivos gravados (apagados se der erro)
        self.names = {info.filename: info for info in archive.infolist()}

    # ------------------------------------------------------------- imagens
    def image(self, name, kind, campaign, title="", visibility="mesa"):
        """Copia imagens/<x> do ZIP para um Asset novo. None se não der."""
        from app.blueprints.uploads import sniff_image
        if not isinstance(name, str):
            return None
        info = self.names.get(name)
        if info is None or not name.startswith("imagens/") or info.file_size > MAX_IMAGE_BYTES:
            return None
        data = self.archive.read(info)
        mimetype, extension = sniff_image(data[:16])
        if mimetype is None:
            return None
        token = secrets.token_hex(16)
        filename = "%s.%s" % (token, extension)
        folder = current_app.config["UPLOAD_DIR"]
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, filename)
        with open(path, "wb") as handle:
            handle.write(data)
        self.written.append(path)
        asset = Asset(token=token, owner_id=self.user.id, campaign_id=campaign.id,
                      kind=kind, title=_text(title, 160), filename=filename, mimetype=mimetype,
                      size=len(data), visibility=visibility if visibility in ("mesa", "mestre") else "mesa")
        db.session.add(asset)
        db.session.flush()
        return asset

    # ------------------------------------------------------------- sistema
    def system(self, raw):
        from app.blueprints.systems import clean_payload
        name = _text(raw.get("nome"), 120) or "Sistema importado"
        data = clean_payload(raw.get("dados") or {})
        for candidate in GameSystem.query.filter(
                (GameSystem.is_preset.is_(True)) | (GameSystem.owner_id == self.user.id)).all():
            if candidate.name == name and candidate.data == data:
                return candidate
        system = GameSystem(name=name, slug=slugify(name), description=_text(raw.get("descricao"), 2000),
                            is_preset=False, owner_id=self.user.id, data=data)
        db.session.add(system)
        db.session.flush()
        return system

    # ------------------------------------------------------------- tudo
    @staticmethod
    def rows(doc, key):
        """Só os itens que são dicionários: arquivo editado à mão não derruba nada."""
        value = doc.get(key)
        return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []

    def run(self, doc):
        info = doc.get("campanha") if isinstance(doc.get("campanha"), dict) else {}
        system = self.system(doc.get("sistema") if isinstance(doc.get("sistema"), dict) else {})
        campaign = Campaign(
            name=_text(info.get("nome"), 160) or "Campanha importada",
            tagline=_text(info.get("subtitulo"), 240),
            description=_text(info.get("descricao"), 20000),
            status=info.get("situacao") if info.get("situacao") in ("ativa", "pausada", "concluida") else "ativa",
            system_id=system.id, master_id=self.user.id, invite_code=Campaign.new_invite_code(),
            calendar=worldcal.normalize(doc.get("calendario")),
            treasure=treasure_helper.normalize(doc.get("tesouro")) if doc.get("tesouro") else None,
        )
        db.session.add(campaign)
        db.session.flush()
        db.session.add(CampaignMember(campaign_id=campaign.id, user_id=self.user.id, role="mestre"))
        master_name = _text(info.get("mestre"), 64)

        character_ids = {}
        for raw in self.rows(doc, "fichas"):
            avatar = str(raw.get("retrato") or "")
            if avatar.startswith("imagens/"):
                asset = self.image(avatar, "avatar", campaign)
                avatar = asset.url if asset else ""
            elif not avatar.startswith("https://"):
                avatar = ""
            owner = _text(raw.get("dono"), 64)
            character = Character(
                name=_text(raw.get("nome"), 160) or "Sem nome",
                kind=raw.get("tipo") if raw.get("tipo") in ("pj", "npc", "criatura") else "pj",
                concept=_text(raw.get("conceito"), 240), avatar_url=avatar[:500],
                owner_id=self.user.id, campaign_id=campaign.id, system_id=system.id,
                visible_to_players=bool(raw.get("visivel_para_jogadores", True)),
                imported_owner=owner if owner and owner != master_name else None,
                data=sheet_helper.normalize(raw.get("dados") if isinstance(raw.get("dados"), dict) else {}),
            )
            db.session.add(character)
            db.session.flush()
            if raw.get("id") is not None:
                character_ids[to_int(raw.get("id"), 0)] = character.id

        map_ids = {}
        for raw in self.rows(doc, "mapas"):
            asset = self.image(raw.get("arquivo"), "mapa", campaign, raw.get("titulo"), raw.get("visibilidade"))
            if asset is not None and raw.get("id") is not None:
                map_ids[to_int(raw.get("id"), 0)] = asset.id

        for raw in self.rows(doc, "sessoes"):
            try:
                when = date.fromisoformat(raw.get("data")) if raw.get("data") else None
            except (TypeError, ValueError):
                when = None
            db.session.add(GameSession(
                campaign_id=campaign.id, number=to_int(raw.get("numero"), 1),
                title=_text(raw.get("titulo"), 200) or "Sessão", scheduled_for=when,
                start_time=_text(raw.get("horario"), 5) or None,
                status=raw.get("situacao") if raw.get("situacao") in ("planejada", "realizada", "cancelada") else "planejada",
                synopsis=_text(raw.get("sinopse"), 50000), plan=_text(raw.get("roteiro_do_mestre"), 50000),
                recap=_text(raw.get("resumo"), 50000),
                beats=raw.get("cenas") if isinstance(raw.get("cenas"), list) else [],
                world_day=raw.get("data_no_mundo") if isinstance(raw.get("data_no_mundo"), int) else None,
                world_minute=_minute(raw.get("hora_no_mundo")),
            ))

        for raw in self.rows(doc, "anotacoes"):
            visibility = raw.get("visibilidade") if raw.get("visibilidade") in ("mesa", "mestre", "jogadores") else "mesa"
            body = _text(raw.get("texto"), 50000)
            if visibility == "jogadores":
                # Os destinatários eram contas do outro site: vira só-mestre até
                # ele escolher de novo para quem mostrar.
                para = ", ".join(str(p) for p in raw.get("para") or [])
                visibility = "mestre"
                body = ("_Era visível para: %s_\n\n" % para if para else "") + body
            tags = raw.get("tags") if isinstance(raw.get("tags"), list) else []
            db.session.add(Note(
                campaign_id=campaign.id, author_id=self.user.id,
                title=_text(raw.get("titulo"), 200) or "Anotação", body=body,
                category=_text(raw.get("categoria"), 40) or "geral",
                tags=_text(", ".join(str(t) for t in tags), 240), visibility=visibility,
                pinned=bool(raw.get("fixada")),
            ))

        for raw in self.rows(doc, "combates"):
            combatants = []
            for c in raw.get("combatentes") or []:
                if not isinstance(c, dict):
                    continue
                c = dict(c)
                c["character_id"] = character_ids.get(to_int(c.get("character_id"), 0))
                c["source_id"] = character_ids.get(to_int(c.get("source_id"), 0))
                c["uid"] = _text(c.get("uid"), 16) or secrets.token_hex(4)
                combatants.append(c)
            board = raw.get("mapa_tatico")
            if isinstance(board, dict):
                board = board_helper.normalize(board)
                board["map_id"] = map_ids.get(to_int(board.get("map_id"), 0))
            db.session.add(Encounter(campaign_id=campaign.id, name=_text(raw.get("nome"), 160) or "Combate",
                                     round_number=max(1, to_int(raw.get("rodada"), 1)),
                                     combatants=combatants, board=board if isinstance(board, dict) else None))

        for raw in self.rows(doc, "linha_do_tempo"):
            db.session.add(TimelineEntry(
                campaign_id=campaign.id, author_id=self.user.id, label=_text(raw.get("quando_no_jogo"), 120),
                title=_text(raw.get("titulo"), 200) or "Acontecimento", body=_text(raw.get("texto"), 50000),
                world_day=raw.get("data_no_mundo") if isinstance(raw.get("data_no_mundo"), int) else None,
                world_minute=_minute(raw.get("hora_no_mundo")),
            ))

        for position, raw in enumerate(self.rows(doc, "relogios")[:30]):
            segments = max(2, min(24, to_int(raw.get("segments"), 6)))
            db.session.add(Clock(
                campaign_id=campaign.id, title=_text(raw.get("title"), 120) or "Relógio",
                segments=segments, filled=max(0, min(segments, to_int(raw.get("filled"), 0))),
                visibility=raw.get("visibility") if raw.get("visibility") in Clock.VISIBILITY else "mesa",
                position=position,
            ))
        return campaign


def import_zip(stream, user):
    """Lê o ZIP e cria a campanha. Levanta ImportError_ com uma mensagem clara."""
    try:
        archive = zipfile.ZipFile(stream)
    except (zipfile.BadZipFile, OSError):
        raise ImportError_("Isso não é um arquivo .zip de exportação do Grimório.")
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise ImportError_("O arquivo tem itens demais.")
        total = sum(i.file_size for i in infos)
        packed = sum(i.compress_size for i in infos) or 1
        if total > MAX_TOTAL_BYTES or total / packed > MAX_RATIO:
            raise ImportError_("O arquivo descompactado ficaria grande demais.")
        try:
            info = archive.getinfo("campanha.json")
        except KeyError:
            raise ImportError_("Não achei o campanha.json dentro do ZIP.")
        if info.file_size > MAX_JSON_BYTES:
            raise ImportError_("O campanha.json é grande demais.")
        try:
            doc = json.loads(archive.read(info).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ImportError_("O campanha.json está corrompido.")
        if not isinstance(doc, dict) or doc.get("formato") != FORMAT:
            raise ImportError_("Este ZIP não é uma exportação de campanha do Grimório.")
        if to_int(doc.get("versao"), 0) not in (1, 2):
            raise ImportError_("Exportação de uma versão mais nova do Grimório: atualize o site.")

        importer = _Importer(archive, user)
        try:
            campaign = importer.run(doc)
            db.session.commit()
        except Exception:
            db.session.rollback()
            for path in importer.written:
                try:
                    os.remove(path)
                except OSError:
                    pass
            raise
        return campaign


def read_upload(storage):
    """Arquivo enviado → stream que o zipfile consegue ler."""
    data = storage.read()
    return io.BytesIO(data)
