# -*- coding: utf-8 -*-
"""Validação do cadastro e proteções gerais das páginas."""
import pytest

from app import create_app
from app.utils import valid_email

PAYLOAD = "</script><script>alert(1)</script>"


def _register(client, email, username="ana"):
    return client.post("/cadastro", data={"username": username, "email": email,
                                          "password": "segredo123", "confirm": "segredo123"})


@pytest.mark.parametrize("email", [
    "ana@exemplo.com", "ana.souza+rpg@mail.exemplo.com.br", "ANA@Exemplo.COM", "a_b-c@x.io",
])
def test_email_valido(email):
    assert valid_email(email.lower())


@pytest.mark.parametrize("email", [
    "", "@", "ana@", "@exemplo.com", "ana@exemplo", "ana exemplo@x.com", "ana@@x.com",
    "ana@x..com", "ana@.x.com", "ana@x.com.", ".ana@x.com", "ana.@x.com", "an..a@x.com",
    "ana@-x.com", "ana@x-.com", "ana@x.c", "<script>@x.com", "ana@x.com\n", "a" * 160 + "@x.com",
])
def test_email_invalido(email):
    assert not valid_email(email)


def test_cadastro_recusa_email_malformado(app):
    client = app.test_client()
    response = _register(client, "ana@exemplo")
    assert response.status_code == 200
    assert "e-mail válido".encode() in response.data
    from app.models import User
    with app.app_context():
        assert User.query.count() == 0


def test_cadastro_normaliza_email(app):
    client = app.test_client()
    assert _register(client, "  Ana@Exemplo.COM ").status_code == 302
    other = app.test_client()
    response = _register(other, "ana@exemplo.com", username="outra")
    assert "já está cadastrado".encode() in response.data


def test_json_da_ficha_nao_fecha_o_script(mesa):
    """Um jogador não pode injetar script na ficha que o mestre vai abrir."""
    campaign_id, code = mesa.campaign("mestre")
    mesa.join("ana", code)
    character_id = mesa.character("ana", campaign_id)
    url = "/fichas/%d" % character_id
    mesa.user("ana").post(url, data={"__action": "add_skill", "new_skill_name": PAYLOAD[:60],
                                     "new_skill_attr": "int"})

    html = mesa.user("mestre").get(url).get_data(as_text=True)
    config = html.split('id="sheet-config"', 1)[1].split("</script>", 1)[0]
    assert "<script>" not in config
    assert "\\u003c/script\\u003e" in config


def test_json_do_editor_de_sistema_nao_fecha_o_script(mesa, app):
    from app.extensions import db
    from app.models import GameSystem
    client = mesa.user("mestre")
    response = client.post("/sistemas/%d/duplicar" % mesa.system_id("ordem-paranormal"))
    system_id = int(response.headers["Location"].rstrip("/").split("/")[-2])
    with app.app_context():
        system = db.session.get(GameSystem, system_id)
        data = dict(system.data)
        data["attributes"] = [dict(data["attributes"][0], name=PAYLOAD)] + data["attributes"][1:]
        system.data = data
        db.session.commit()
    html = client.get("/sistemas/%d/editar" % system_id).get_data(as_text=True)
    payload = html.split('id="system-data"', 1)[1].split("</script>", 1)[0]
    assert "<script>" not in payload


def test_cabecalhos_de_seguranca(app):
    response = app.test_client().get("/entrar")
    assert response.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert "Strict-Transport-Security" not in response.headers  # só em HTTPS


def test_hsts_em_https(app):
    response = app.test_client().get("/entrar", base_url="https://localhost")
    assert "max-age=" in response.headers["Strict-Transport-Security"]


def test_producao_sem_secret_key_nao_sobe():
    from config import Config

    class SemChave(Config):
        SECRET_KEY = Config.DEFAULT_SECRET_KEY
        SESSION_COOKIE_SECURE = True
        AUTO_MIGRATE = False

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app(SemChave)
