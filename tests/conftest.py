# -*- coding: utf-8 -*-
"""Base dos testes.

Cada teste roda num banco SQLite próprio. Para não pagar as migrações em todo
teste, um banco-modelo é migrado uma vez por sessão e copiado para cada teste.
"""
import io
import os
import re
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from config import Config  # noqa: E402

PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def make_config(db_path, tmp_path, csrf=False):
    class TestConfig(Config):
        TESTING = True
        SECRET_KEY = "teste"
        SQLALCHEMY_DATABASE_URI = "sqlite:///" + db_path.replace("\\", "/")
        WTF_CSRF_ENABLED = csrf
        UPLOAD_DIR = str(tmp_path / "uploads")
        BACKUP_DIR = str(tmp_path / "backups")
        BACKUP_KEEP = 3
        AUTO_MAINTENANCE = False  # os testes que precisam ligam na mão
    return TestConfig


@pytest.fixture(scope="session")
def template_db(tmp_path_factory):
    from app import create_app
    folder = tmp_path_factory.mktemp("modelo")
    path = str(folder / "modelo.db")
    create_app(make_config(path, folder))
    return path


@pytest.fixture
def app(template_db, tmp_path):
    from app import create_app
    path = str(tmp_path / "teste.db")
    shutil.copy(template_db, path)
    application = create_app(make_config(path, tmp_path))
    yield application


@pytest.fixture
def csrf_app(template_db, tmp_path):
    from app import create_app
    path = str(tmp_path / "csrf.db")
    shutil.copy(template_db, path)
    return create_app(make_config(path, tmp_path, csrf=True))


# ------------------------------------------------------------------ ajudantes
class Mesa(object):
    """Atalhos para montar cenários: usuários, campanhas, fichas."""

    def __init__(self, app):
        self.app = app
        self.clients = {}

    def user(self, username):
        if username not in self.clients:
            client = self.app.test_client()
            response = client.post("/cadastro", data={
                "username": username, "email": "%s@teste.dev" % username,
                "password": "segredo123", "confirm": "segredo123",
            })
            assert response.status_code == 302, response.data[:300]
            self.clients[username] = client
        return self.clients[username]

    def system_id(self, slug):
        from app.models import GameSystem
        with self.app.app_context():
            return GameSystem.query.filter_by(slug=slug, is_preset=True).first().id

    def campaign(self, master, slug="ordem-paranormal", name="Campanha"):
        from app.models import Campaign
        client = self.user(master)
        client.post("/campanhas/nova", data={"name": name, "system_id": self.system_id(slug)})
        with self.app.app_context():
            campaign = Campaign.query.filter_by(name=name).order_by(Campaign.id.desc()).first()
            return campaign.id, campaign.invite_code

    def join(self, username, code):
        response = self.user(username).post("/campanhas/entrar", data={"invite_code": code})
        assert response.status_code == 302

    def character(self, owner, campaign_id=None, name="Kian", kind="pj", slug=None):
        from app.models import Character
        data = {"name": name, "kind": kind}
        if campaign_id:
            data["campaign_id"] = campaign_id
        else:
            data["system_id"] = self.system_id(slug or "ordem-paranormal")
        response = self.user(owner).post("/fichas/nova", data=data)
        assert response.status_code == 302, response.data[:300]
        with self.app.app_context():
            return Character.query.filter_by(name=name).order_by(Character.id.desc()).first().id

    def get(self, model, pk):
        from app.extensions import db
        with self.app.app_context():
            obj = db.session.get(model, pk)
            db.session.expunge(obj)
            return obj

    def sheet(self, character_id):
        from app.models import Character
        return self.get(Character, character_id)

    def autosave(self, username, character_id, **fields):
        return self.user(username).post(
            "/fichas/%d" % character_id, data=fields, headers={"X-Requested-With": "fetch"}
        )


@pytest.fixture
def mesa(app):
    return Mesa(app)


def png_file(name="retrato.png"):
    return (io.BytesIO(PNG_1PX), name)


def csrf_from(html):
    match = re.search(rb'name="csrf_token" value="([^"]+)"', html)
    assert match, "token CSRF não encontrado na página"
    return match.group(1).decode()
