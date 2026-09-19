import json
import secrets
from datetime import datetime, date, timedelta

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db
from app.utils import local_time


class JSONField(db.TypeDecorator):
    """Campo JSON portátil (funciona igual em SQLite e no MySQL do PythonAnywhere)."""

    impl = db.Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if not value:
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    # Sobe ao trocar a senha ou pedir "sair de todos os aparelhos": vai dentro do
    # cookie de sessão (get_id), e cookie com número velho deixa de valer.
    session_version = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    systems = db.relationship("GameSystem", back_populates="owner", lazy="dynamic")
    characters = db.relationship("Character", back_populates="owner", lazy="dynamic")
    memberships = db.relationship(
        "CampaignMember", back_populates="user", lazy="dynamic", cascade="all, delete-orphan"
    )

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    def get_id(self):
        return "%d:%d" % (self.id, self.session_version or 0)

    def end_other_sessions(self):
        self.session_version = (self.session_version or 0) + 1

    @property
    def campaigns(self):
        return [m.campaign for m in self.memberships.all() if m.campaign]

    def __repr__(self):
        return "<User %s>" % self.username


class GameSystem(db.Model):
    """Modelo de ficha: define atributos, barras, perícias e campos livres."""

    __tablename__ = "game_systems"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(120), index=True)
    description = db.Column(db.Text, default="")
    is_preset = db.Column(db.Boolean, default=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    data = db.Column(JSONField, default=dict)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship("User", back_populates="systems")
    campaigns = db.relationship("Campaign", back_populates="system", lazy="dynamic")

    @property
    def attributes(self):
        return (self.data or {}).get("attributes", [])

    @property
    def bars(self):
        return (self.data or {}).get("bars", [])

    @property
    def skills(self):
        return (self.data or {}).get("skills", [])

    @property
    def meta_fields(self):
        return (self.data or {}).get("meta_fields", [])

    @property
    def roll(self):
        return (self.data or {}).get("roll", {"type": "d20", "label": "d20 + mod"})

    def editable_by(self, user):
        return user.is_authenticated and not self.is_preset and self.owner_id == user.id

    def usable_by(self, user):
        return self.is_preset or (user.is_authenticated and self.owner_id == user.id)

    def __repr__(self):
        return "<GameSystem %s>" % self.name


class Campaign(db.Model):
    __tablename__ = "campaigns"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    tagline = db.Column(db.String(240), default="")
    description = db.Column(db.Text, default="")
    system_id = db.Column(db.Integer, db.ForeignKey("game_systems.id"), nullable=False)
    master_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    invite_code = db.Column(db.String(12), unique=True, index=True)
    status = db.Column(db.String(24), default="ativa")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # "Mostrar para a mesa": o último handout que o mestre abriu na tela de todos.
    spotlight = db.Column(JSONField, nullable=True)
    # Tesouro do grupo (itens, moedas e registro) — separado das fichas.
    treasure = db.Column(JSONField, nullable=True)
    # Calendário do mundo: meses, dias da semana, era e a data de "hoje" no jogo.
    calendar = db.Column(JSONField, nullable=True)

    system = db.relationship("GameSystem", back_populates="campaigns")
    master = db.relationship("User", foreign_keys=[master_id])
    members = db.relationship(
        "CampaignMember", back_populates="campaign", cascade="all, delete-orphan", lazy="dynamic"
    )
    characters = db.relationship(
        "Character", back_populates="campaign", cascade="all, delete-orphan", lazy="dynamic"
    )
    sessions = db.relationship(
        "GameSession", back_populates="campaign", cascade="all, delete-orphan", lazy="dynamic"
    )
    notes = db.relationship(
        "Note", back_populates="campaign", cascade="all, delete-orphan", lazy="dynamic"
    )
    encounters = db.relationship(
        "Encounter", back_populates="campaign", cascade="all, delete-orphan", lazy="dynamic"
    )
    timeline = db.relationship(
        "TimelineEntry", back_populates="campaign", cascade="all, delete-orphan", lazy="dynamic"
    )
    rolls = db.relationship(
        "RollLog", back_populates="campaign", cascade="all, delete-orphan", lazy="dynamic"
    )
    assets = db.relationship(
        "Asset", back_populates="campaign", cascade="all, delete-orphan", lazy="dynamic"
    )
    clocks = db.relationship(
        "Clock", back_populates="campaign", cascade="all, delete-orphan", lazy="dynamic",
        order_by="Clock.position, Clock.id",
    )

    @staticmethod
    def new_invite_code():
        while True:
            code = secrets.token_hex(3).upper()
            if not Campaign.query.filter_by(invite_code=code).first():
                return code

    def is_master(self, user):
        return bool(getattr(user, "is_authenticated", False)) and user.id == self.master_id

    def membership(self, user):
        if not getattr(user, "is_authenticated", False):
            return None
        return self.members.filter_by(user_id=user.id).first()

    def can_view(self, user):
        return self.is_master(user) or self.membership(user) is not None

    @property
    def next_session(self):
        return (
            self.sessions.filter(GameSession.status == "planejada")
            .order_by(GameSession.scheduled_for.is_(None), GameSession.scheduled_for.asc())
            .first()
        )

    def __repr__(self):
        return "<Campaign %s>" % self.name


class CampaignMember(db.Model):
    __tablename__ = "campaign_members"
    __table_args__ = (db.UniqueConstraint("campaign_id", "user_id", name="uq_member"),)

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    role = db.Column(db.String(16), default="jogador")
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

    campaign = db.relationship("Campaign", back_populates="members")
    user = db.relationship("User", back_populates="memberships")


class Character(db.Model):
    __tablename__ = "characters"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(16), default="pj", index=True)
    concept = db.Column(db.String(240), default="")
    avatar_url = db.Column(db.String(500), default="")
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=True)
    system_id = db.Column(db.Integer, db.ForeignKey("game_systems.id"), nullable=False)
    visible_to_players = db.Column(db.Boolean, default=True)
    # Ficha vinda de uma campanha importada: nome de usuário do dono original,
    # até o mestre entregá-la a alguém da mesa.
    imported_owner = db.Column(db.String(64), nullable=True)
    data = db.Column(JSONField, default=dict)
    # Sobe a cada gravação. Quem salva com uma versão velha está editando por
    # cima de uma mudança que não viu — ver blueprints/characters.py.
    version = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = db.relationship("User", back_populates="characters")
    campaign = db.relationship("Campaign", back_populates="characters")
    system = db.relationship("GameSystem")
    revisions = db.relationship(
        "CharacterRevision", cascade="all, delete-orphan", lazy="dynamic",
        order_by="CharacterRevision.id.desc()",
    )

    def editable_by(self, user):
        if not getattr(user, "is_authenticated", False):
            return False
        if self.owner_id == user.id:
            return True
        return bool(self.campaign and self.campaign.is_master(user))

    def viewable_by(self, user):
        if self.editable_by(user):
            return True
        if not self.campaign:
            return False
        return bool(self.visible_to_players and self.campaign.can_view(user))

    def bump_version(self):
        self.version = (self.version or 1) + 1

    def __repr__(self):
        return "<Character %s>" % self.name


class GameSession(db.Model):
    __tablename__ = "game_sessions"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    number = db.Column(db.Integer, default=1)
    title = db.Column(db.String(200), nullable=False)
    scheduled_for = db.Column(db.Date, nullable=True)
    start_time = db.Column(db.String(5), nullable=True)  # "19:30"
    status = db.Column(db.String(20), default="planejada")
    synopsis = db.Column(db.Text, default="")
    plan = db.Column(db.Text, default="")
    recap = db.Column(db.Text, default="")
    beats = db.Column(JSONField, default=list)
    world_day = db.Column(db.Integer, nullable=True)  # data no calendário do mundo
    reminded_at = db.Column(db.DateTime, nullable=True)  # lembrete por e-mail já enviado
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    campaign = db.relationship("Campaign", back_populates="sessions")
    attendance = db.relationship(
        "SessionAttendance", back_populates="session", cascade="all, delete-orphan", lazy="dynamic"
    )

    def attendance_of(self, user):
        if not getattr(user, "is_authenticated", False):
            return None
        return self.attendance.filter_by(user_id=user.id).first()

    @property
    def progress(self):
        items = self.beats or []
        if not items:
            return 0
        done = len([b for b in items if b.get("done")])
        return int(done * 100 / len(items))

    @property
    def is_late(self):
        return bool(
            self.status == "planejada"
            and self.scheduled_for is not None
            and self.scheduled_for < date.today()
        )


class Note(db.Model):
    __tablename__ = "notes"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, default="")
    category = db.Column(db.String(40), default="geral")
    tags = db.Column(db.String(240), default="")
    # mesa | mestre | jogadores | privada (diário: só quem escreveu — nem o mestre)
    visibility = db.Column(db.String(16), default="mesa")
    revealed_at = db.Column(db.DateTime, nullable=True)
    pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    campaign = db.relationship("Campaign", back_populates="notes")
    author = db.relationship("User")
    recipients = db.relationship(
        "NoteRecipient", back_populates="note", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def recipient_ids(self):
        return {r.user_id for r in self.recipients}

    def visible_to(self, user, is_master):
        if self.author_id == getattr(user, "id", None):
            return True
        if self.visibility == "privada":
            return False  # nem o mestre
        if is_master:
            return True
        if self.visibility == "mesa":
            return True
        if self.visibility == "jogadores":
            return getattr(user, "id", None) in self.recipient_ids
        return False

    @property
    def recently_revealed(self):
        return bool(self.revealed_at and datetime.utcnow() - self.revealed_at < timedelta(days=3))

    @property
    def tag_list(self):
        return [t.strip() for t in (self.tags or "").split(",") if t.strip()]


class Encounter(db.Model):
    """Rastreador de combate / iniciativa."""

    __tablename__ = "encounters"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    round_number = db.Column(db.Integer, default=1)
    turn_index = db.Column(db.Integer, default=0)
    combatants = db.Column(JSONField, default=list)
    # Mapa tático: imagem, grade, posições das fichas e névoa. Coluna separada
    # dos combatentes para mover uma ficha não brigar com o rastreador.
    board = db.Column(JSONField, nullable=True)
    # Combate preparado para uma sessão (roteiro do mestre).
    session_id = db.Column(db.Integer, db.ForeignKey("game_sessions.id", ondelete="SET NULL"),
                           nullable=True)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    campaign = db.relationship("Campaign", back_populates="encounters")
    session = db.relationship("GameSession")


class TimelineEntry(db.Model):
    """Linha do tempo / diário de bordo da campanha."""

    __tablename__ = "timeline_entries"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    label = db.Column(db.String(120), default="")
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, default="")
    world_day = db.Column(db.Integer, nullable=True)  # data no calendário do mundo
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    campaign = db.relationship("Campaign", back_populates="timeline")
    author = db.relationship("User")


class Clock(db.Model):
    """Relógio de progresso: "o ritual se completa em 6 segmentos"."""

    __tablename__ = "clocks"

    VISIBILITY = ("mesa", "mestre")

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    segments = db.Column(db.Integer, nullable=False, default=6)
    filled = db.Column(db.Integer, nullable=False, default=0)
    color = db.Column(db.String(9), default="#f0a94b")
    visibility = db.Column(db.String(12), default="mesa")
    position = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    campaign = db.relationship("Campaign", back_populates="clocks")

    def as_dict(self):
        return {"id": self.id, "title": self.title, "segments": self.segments,
                "filled": self.filled, "color": self.color, "visibility": self.visibility}


class NoteRecipient(db.Model):
    """Jogador específico que pode ler uma anotação com visibilidade "jogadores"."""

    __tablename__ = "note_recipients"
    __table_args__ = (db.UniqueConstraint("note_id", "user_id", name="uq_note_recipient"),)

    id = db.Column(db.Integer, primary_key=True)
    note_id = db.Column(db.Integer, db.ForeignKey("notes.id", ondelete="CASCADE"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    note = db.relationship("Note", back_populates="recipients")
    user = db.relationship("User")


class SessionAttendance(db.Model):
    """Confirmação de presença de um jogador numa sessão."""

    __tablename__ = "session_attendance"
    __table_args__ = (db.UniqueConstraint("session_id", "user_id", name="uq_attendance"),)

    STATUSES = [("vou", "Vou"), ("talvez", "Talvez"), ("nao", "Não posso")]

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer, db.ForeignKey("game_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    status = db.Column(db.String(12), nullable=False, default="vou")
    comment = db.Column(db.String(200), default="")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    session = db.relationship("GameSession", back_populates="attendance")
    user = db.relationship("User")

    @property
    def label(self):
        return dict(self.STATUSES).get(self.status, self.status)


class RollLog(db.Model):
    """Rolagem feita no servidor e compartilhada com a mesa."""

    __tablename__ = "roll_logs"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(
        db.Integer, db.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    character_id = db.Column(
        db.Integer, db.ForeignKey("characters.id", ondelete="SET NULL"), nullable=True
    )
    label = db.Column(db.String(120), nullable=False)
    result = db.Column(db.String(40), nullable=False)
    detail = db.Column(db.String(400), default="")
    flag = db.Column(db.String(8), default="")  # crit | fail | vazio
    secret = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    campaign = db.relationship("Campaign", back_populates="rolls")
    user = db.relationship("User")
    character = db.relationship("Character")

    def visible_to(self, user, is_master):
        return not self.secret or is_master or self.user_id == getattr(user, "id", None)

    def as_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "result": self.result,
            "detail": self.detail,
            "flag": self.flag,
            "secret": bool(self.secret),
            "who": self.character.name if self.character else self.user.username,
            "user": self.user.username,
            "at": local_time(self.created_at, "%H:%M"),
            # ISO em UTC: o navegador mostra no fuso de quem está vendo.
            "at_iso": self.created_at.isoformat() + "Z",
        }


class Asset(db.Model):
    """Arquivo enviado: retrato de personagem ou mapa/imagem da campanha."""

    __tablename__ = "assets"

    KINDS = ("avatar", "mapa")

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(32), unique=True, nullable=False, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    campaign_id = db.Column(
        db.Integer, db.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True
    )
    kind = db.Column(db.String(12), nullable=False, default="mapa")
    title = db.Column(db.String(160), default="")
    filename = db.Column(db.String(80), nullable=False)
    mimetype = db.Column(db.String(40), nullable=False)
    size = db.Column(db.Integer, default=0)
    visibility = db.Column(db.String(12), default="mesa")  # mesa | mestre
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship("User")
    campaign = db.relationship("Campaign", back_populates="assets")

    URL_PREFIX = "/arquivos/"

    @property
    def url(self):
        # Caminho fixo em vez de url_for: vai gravado no banco (avatar_url) e
        # precisa funcionar fora de uma requisição. A rota uploads.serve usa o
        # mesmo prefixo.
        return self.URL_PREFIX + self.token


class CharacterRevision(db.Model):
    """Estado de uma ficha antes de uma leva de alterações — permite desfazer.

    Criada automaticamente (ver app/revisions.py) sempre que o JSON da ficha
    muda, venha a mudança de onde vier: a própria ficha, o combate, o XP da
    sessão. Edições seguidas da mesma pessoa viram uma revisão só.
    """

    __tablename__ = "character_revisions"

    id = db.Column(db.Integer, primary_key=True)
    character_id = db.Column(
        db.Integer, db.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1)
    data = db.Column(JSONField, nullable=False)
    changed = db.Column(db.String(300), default="")   # seções alteradas depois deste estado
    reason = db.Column(db.String(40), default="edição")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship("User")

    @property
    def changed_list(self):
        return [c for c in (self.changed or "").split(",") if c]


class LoginAttempt(db.Model):
    """Tentativa de login, para frear quem fica chutando senha."""

    __tablename__ = "login_attempts"

    id = db.Column(db.Integer, primary_key=True)
    identifier = db.Column(db.String(160), nullable=False, index=True)
    ip = db.Column(db.String(64), nullable=False, index=True)
    success = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class RandomTable(db.Model):
    """Tabela aleatória do mestre: "Encontros na estrada", "Nomes de taverna"."""

    __tablename__ = "random_tables"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    # [{"min": 1, "max": 3, "text": "Lobos"}] — faixas do dado (ver app/tables.py)
    entries = db.Column(JSONField, default=list)
    visibility = db.Column(db.String(12), default="mestre")  # mesa | mestre
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    campaign = db.relationship("Campaign", backref=db.backref(
        "random_tables", lazy="dynamic", cascade="all, delete-orphan"))


class Whisper(db.Model):
    """Sussurro: mensagem entre um jogador e o mestre que a mesa não vê."""

    __tablename__ = "whispers"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id", ondelete="CASCADE"),
                            nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    text = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship("User", foreign_keys=[sender_id])
    recipient = db.relationship("User", foreign_keys=[recipient_id])

    def as_dict(self):
        return {"id": self.id, "from": self.sender.username, "from_id": self.sender_id,
                "to": self.recipient.username, "to_id": self.recipient_id, "text": self.text,
                "at_iso": self.created_at.isoformat() + "Z"}


class ErrorReport(db.Model):
    """Erro 500 registrado para o administrador ver (sem depender de e-mail)."""

    __tablename__ = "error_reports"

    id = db.Column(db.Integer, primary_key=True)
    signature = db.Column(db.String(40), unique=True, nullable=False)  # agrupa o mesmo erro
    path = db.Column(db.String(300), default="")
    method = db.Column(db.String(10), default="")
    user_id = db.Column(db.Integer, nullable=True)
    summary = db.Column(db.String(300), default="")
    traceback = db.Column(db.Text, default="")
    count = db.Column(db.Integer, default=1)
    first_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class SiteSetting(db.Model):
    """Pares chave/valor do site (ex.: quando o último backup foi baixado)."""

    __tablename__ = "site_settings"

    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.Text, default="")

    @staticmethod
    def get(key, default=None):
        row = db.session.get(SiteSetting, key)
        return row.value if row is not None else default

    @staticmethod
    def put(key, value):
        row = db.session.get(SiteSetting, key)
        if row is None:
            db.session.add(SiteSetting(key=key, value=str(value)))
        else:
            row.value = str(value)
