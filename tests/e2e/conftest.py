# -*- coding: utf-8 -*-
"""Testes no navegador de verdade (Playwright).

Os testes de servidor não pegam bug de JavaScript — e os dois bugs mais
chatos até agora (o "Salvando…" infinito e o "Próximo turno" que não andava)
eram de JavaScript. Aqui o site roda de verdade numa porta local, com CSRF
ligado como em produção, e um navegador sem janela clica nas telas.

Usa o Edge ou o Chrome já instalado na máquina (nada é baixado):
    E2E_BROWSER=msedge (padrão) | chrome | chromium
Sem Playwright ou sem navegador, os testes são pulados — não falham.
Para rodar só eles:   python -m pytest tests/e2e
Para pular:           python -m pytest -m "not e2e"
"""
import os
import re
import threading

import pytest

from tests.conftest import make_config

pytestmark = pytest.mark.e2e
PASSWORD = "senha-de-teste-1"


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """O site inteiro rodando numa thread, com banco e uploads próprios."""
    from werkzeug.serving import make_server
    from app import create_app

    folder = tmp_path_factory.mktemp("e2e")
    config = make_config(str(folder / "e2e.db"), folder, csrf=True)
    config.TESTING = False  # como em produção (erros viram 500, não exceção)
    app = create_app(config)
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % server.server_port
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright não instalado (pip install -r requirements-dev.txt)")
    manager = sync_playwright().start()
    channel = os.environ.get("E2E_BROWSER", "msedge")
    try:
        launched = manager.chromium.launch(channel=None if channel == "chromium" else channel,
                                           headless=os.environ.get("E2E_HEADED") != "1")
    except Exception as error:  # navegador não instalado
        manager.stop()
        pytest.skip("Navegador para os testes não encontrado (%s): %s" % (channel, str(error)[:120]))
    yield launched
    launched.close()
    manager.stop()


class Person(object):
    """Uma pessoa com o próprio navegador (cookies separados)."""

    def __init__(self, browser, base, name):
        self.base, self.name = base, name
        self.context = browser.new_context(viewport={"width": 1280, "height": 900}, locale="pt-BR")
        self.context.set_default_timeout(10000)
        self.page = self.context.new_page()
        self.page.on("dialog", lambda dialog: dialog.accept())  # confirm() sempre "OK"
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))

    def go(self, path):
        self.page.goto(self.base + path)
        return self.page

    def register(self):
        page = self.go("/cadastro")
        page.fill("#username", self.name)
        page.fill("#email", "%s@exemplo.com" % self.name)
        page.fill("#password", PASSWORD)
        page.fill("#confirm", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_url(re.compile(r"/painel"))
        return self

    def create_campaign(self, name, system="D&D 5ª Edição"):
        page = self.go("/campanhas/nova")
        page.fill("#name", name)
        value = page.locator("#system_id option", has_text=system).first.get_attribute("value")
        page.select_option("#system_id", value)
        page.click("button[type=submit]")
        page.wait_for_url(re.compile(r"/campanhas/\d+$"))
        return int(page.url.rsplit("/", 1)[1])

    def join(self, campaign_id, master):
        code = master.go("/campanhas/%d" % campaign_id).inner_text(".code-pill").strip()
        page = self.go("/campanhas/convite/%s" % code)
        page.click("text=Entrar na campanha")
        page.wait_for_url(re.compile(r"/campanhas/%d" % campaign_id))

    def create_character(self, name, campaign_id=None, kind="pj"):
        page = self.go("/fichas/nova" + ("?campanha=%d" % campaign_id if campaign_id else ""))
        page.fill("#name", name)
        page.select_option("#kind", kind)
        page.click("form button[type=submit]")
        page.wait_for_url(re.compile(r"/fichas/\d+$"))
        return int(page.url.rsplit("/", 1)[1])

    def close(self):
        self.context.close()


@pytest.fixture
def people(browser, live_server):
    created = []

    def make(name):
        person = Person(browser, live_server, name)
        created.append(person)
        return person
    yield make
    for person in created:
        assert not person.errors, "Erro de JavaScript em %s: %s" % (person.name, person.errors)
        person.close()
