# -*- coding: utf-8 -*-
"""Recuperar a senha por e-mail."""
import re

import pytest


def outbox(app):
    return app.extensions.setdefault("outbox", [])


def link_from(message):
    return re.search(r"https?://\S+/redefinir-senha/\S+", message["body"]).group(0)


def test_fluxo_completo(mesa, app):
    mesa.user("ana")
    anonymous = app.test_client()
    response = anonymous.post("/esqueci-senha", data={"email": "ANA@teste.dev "})
    assert response.status_code == 302
    assert len(outbox(app)) == 1
    message = outbox(app)[0]
    assert message["to"] == "ana@teste.dev" and "redefinir" in message["subject"]
    path = link_from(message).split("localhost", 1)[1]

    page = anonymous.get(path)
    assert page.status_code == 200 and b"ana" in page.data
    assert b"conferem" in anonymous.post(path, data={"password": "novasenha1", "confirm": "outra"},
                                         follow_redirects=True).data
    done = anonymous.post(path, data={"password": "novasenha1", "confirm": "novasenha1"})
    assert done.status_code == 302

    login = app.test_client().post("/entrar", data={"identifier": "ana", "password": "novasenha1"})
    assert login.status_code == 302
    old = app.test_client().post("/entrar", data={"identifier": "ana", "password": "segredo123"})
    assert old.status_code == 401

    # O link só vale uma vez.
    again = anonymous.get(path)
    assert again.status_code == 302 and "/esqueci-senha" in again.headers["Location"]


def test_mesma_resposta_para_email_inexistente(mesa, app):
    mesa.user("ana")
    client = app.test_client()
    known = client.post("/esqueci-senha", data={"email": "ana@teste.dev"}, follow_redirects=True)
    unknown = client.post("/esqueci-senha", data={"email": "ninguem@teste.dev"}, follow_redirects=True)
    assert len(outbox(app)) == 1
    text = "Se houver uma conta com esse e-mail"
    assert text in known.get_data(as_text=True) and text in unknown.get_data(as_text=True)


def test_link_adulterado_ou_vencido(mesa, app, monkeypatch):
    from app.blueprints import auth
    mesa.user("ana")
    client = app.test_client()
    client.post("/esqueci-senha", data={"email": "ana@teste.dev"})
    path = link_from(outbox(app)[0]).split("localhost", 1)[1]
    assert client.get(path[:-3] + "xyz").status_code == 302  # assinatura inválida

    monkeypatch.setattr(auth, "RESET_MAX_AGE", -1)
    assert client.get(path).status_code == 302  # vencido


def test_limite_de_pedidos(mesa, app):
    mesa.user("ana")
    client = app.test_client()
    for _ in range(3):
        client.post("/esqueci-senha", data={"email": "ana@teste.dev"})
    blocked = client.post("/esqueci-senha", data={"email": "ana@teste.dev"})
    assert blocked.status_code == 429
    assert len(outbox(app)) == 3


def test_link_usa_site_url(mesa, app):
    mesa.user("ana")
    app.config["SITE_URL"] = "https://meusite.exemplo"
    app.test_client().post("/esqueci-senha", data={"email": "ana@teste.dev"},
                           headers={"Host": "site-do-golpista.com"})
    assert link_from(outbox(app)[0]).startswith("https://meusite.exemplo/redefinir-senha/")


def test_sem_email_configurado_explica(mesa, app):
    app.testing = False
    try:
        page = app.test_client().get("/esqueci-senha").get_data(as_text=True)
    finally:
        app.testing = True
    assert "não está configurado" in page and "redefinir-senha" in page
