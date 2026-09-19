# -*- coding: utf-8 -*-
"""Relógios, "mostrar para a mesa", tesouro do grupo e calendário do mundo."""
import threading

from app import worldcal
from app.models import Asset, Campaign, Note

from tests.conftest import png_file


def mesa_completa(mesa, slug="dnd-5e"):
    camp, code = mesa.campaign("mestre", slug=slug)
    mesa.join("ana", code)
    mesa.join("bia", code)
    kian = mesa.character("ana", camp, name="Kian")
    lia = mesa.character("bia", camp, name="Lia")
    return camp, kian, lia


def live(client, camp, spec):
    return client.get("/campanhas/%d/ao-vivo?s=%s" % (camp, spec)).get_json()["sections"]


# ------------------------------------------------------------------ relógios
def test_relogios_mestre_cria_e_a_mesa_ve(mesa):
    camp, *_ = mesa_completa(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    url = "/campanhas/%d/relogios" % camp
    clocks = mestre.post(url, json={"title": "O ritual", "segments": 6}).get_json()["clocks"]
    ritual = clocks[0]
    assert (ritual["title"], ritual["segments"], ritual["filled"]) == ("O ritual", 6, 0)
    mestre.post(url, json={"title": "Plano secreto", "segments": 4, "visibility": "mestre"})

    visto = live(ana, camp, "clocks::")["clocks:"]["data"]
    assert [c["title"] for c in visto] == ["O ritual"]  # o secreto não chega

    mestre.post("%s/%d" % (url, ritual["id"]), json={"delta": 2})
    state = mestre.post("%s/%d" % (url, ritual["id"]), json={"filled": 99}).get_json()["clocks"]
    assert state[0]["filled"] == 6  # não passa do total
    assert mestre.post("%s/%d" % (url, ritual["id"]), json={"title": "  "}).status_code == 400

    assert ana.post(url, json={"title": "meu"}).status_code == 403
    assert ana.post("%s/%d" % (url, ritual["id"]), json={"delta": 1}).status_code == 403

    mestre.post("%s/%d" % (url, ritual["id"]), json={"delete": True})
    assert [c["title"] for c in live(mestre, camp, "clocks::")["clocks:"]["data"]] == ["Plano secreto"]


def test_relogio_de_outra_campanha_nao_e_alterado(mesa):
    camp, *_ = mesa_completa(mesa)
    outra, _ = mesa.campaign("outro", name="Outra")
    clock = mesa.user("outro").post("/campanhas/%d/relogios" % outra,
                                    json={"title": "Deles"}).get_json()["clocks"][0]
    response = mesa.user("mestre").post("/campanhas/%d/relogios/%d" % (camp, clock["id"]),
                                        json={"delta": 1})
    assert response.status_code == 404


# ----------------------------------------------------------- mostrar para a mesa
def test_mostrar_anotacao_secreta_revela_e_abre_para_todos(mesa, app):
    camp, *_ = mesa_completa(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    mestre.post("/campanhas/%d/anotacoes/nova" % camp, data={
        "title": "Carta do duque", "body": "**Traição** à meia-noite", "visibility": "mestre"})
    with app.app_context():
        note_id = Note.query.filter_by(title="Carta do duque").one().id

    assert live(ana, camp, "spot::")["spot:"] == {"same": True}
    response = mestre.post("/campanhas/%d/mostrar" % camp, data={"kind": "anotacao", "id": note_id})
    assert response.status_code == 302

    spot = live(ana, camp, "spot::")["spot:"]
    assert spot["data"]["title"] == "Carta do duque"
    assert "<strong>Traição</strong>" in spot["data"]["html"]
    assert spot["mark"] == str(spot["data"]["seq"])
    # Já visto: não reenvia.
    assert live(ana, camp, "spot::%s" % spot["mark"])["spot:"] == {"same": True}
    with app.app_context():
        from app.extensions import db
        note = db.session.get(Note, note_id)
        assert note.visibility == "mesa" and note.revealed_at is not None


def test_mostrar_imagem_escondida(mesa, app):
    camp, *_ = mesa_completa(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    mestre.post("/campanhas/%d/mapas" % camp, data={
        "title": "Retrato do vilão", "visibility": "mestre", "file": png_file()},
        content_type="multipart/form-data")
    with app.app_context():
        asset = Asset.query.filter_by(title="Retrato do vilão").one()
        asset_id, url = asset.id, asset.url
    assert ana.get(url).status_code == 404
    mestre.post("/campanhas/%d/mostrar" % camp, data={"kind": "mapa", "id": asset_id})
    spot = live(ana, camp, "spot::")["spot:"]["data"]
    assert spot["image"] == url and spot["by"] != 0
    response = ana.get(url)
    assert response.status_code == 200
    response.close()


def test_so_o_mestre_mostra(mesa, app):
    camp, *_ = mesa_completa(mesa)
    ana = mesa.user("ana")
    ana.post("/campanhas/%d/anotacoes/nova" % camp, data={"title": "Minha", "body": "x"})
    with app.app_context():
        note_id = Note.query.filter_by(title="Minha").one().id
    assert ana.post("/campanhas/%d/mostrar" % camp, data={"kind": "anotacao", "id": note_id}).status_code == 403


def test_handout_antigo_nao_reaparece(mesa, app):
    from datetime import datetime, timedelta
    from app.extensions import db
    camp, *_ = mesa_completa(mesa)
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/anotacoes/nova" % camp, data={"title": "Velha", "body": "x"})
    with app.app_context():
        note_id = Note.query.filter_by(title="Velha").one().id
    mestre.post("/campanhas/%d/mostrar" % camp, data={"kind": "anotacao", "id": note_id})
    with app.app_context():
        campaign = db.session.get(Campaign, camp)
        spot = dict(campaign.spotlight)
        spot["at"] = (datetime.utcnow() - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        campaign.spotlight = spot
        db.session.commit()
    assert live(mesa.user("ana"), camp, "spot::")["spot:"] == {"same": True}


# ------------------------------------------------------------ tesouro do grupo
def tesouro(client, camp, **body):
    return client.post("/campanhas/%d/tesouro" % camp, json=body)


def test_tesouro_moedas_itens_e_registro(mesa):
    camp, kian, lia = mesa_completa(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    state = tesouro(ana, camp, op="coins", deltas={"po": 103, "pp": 5, "inexistente": 9},
                    reason="covil do dragão").get_json()["treasure"]
    coins = {c["key"]: c["amount"] for c in state["coins"]}
    assert coins["po"] == 103 and coins["pp"] == 5 and "inexistente" not in coins
    assert "covil do dragão" in state["log"][0]["text"] and state["log"][0]["who"] == "ana"

    assert tesouro(ana, camp, op="coins", deltas={"po": -500}).status_code == 400

    state = tesouro(mestre, camp, op="add_item", name="Poção de cura", qty=3, weight=0.5,
                    value="50 PO").get_json()["treasure"]
    item = state["items"][0]
    assert (item["name"], item["qty"], state["weight"]) == ("Poção de cura", 3, 1.5)
    assert tesouro(ana, camp, op="add_item", name="  ").status_code == 400

    state = tesouro(ana, camp, op="give_item", id=item["id"], to=lia, qty=2).get_json()["treasure"]
    assert state["items"][0]["qty"] == 1
    assert "entregou 2× Poção de cura a Lia" in state["log"][0]["text"]
    assert tesouro(ana, camp, op="give_item", id=item["id"], to=lia, qty=5).status_code == 400
    assert tesouro(ana, camp, op="give_item", id=item["id"], to=99999).status_code == 400
    state = tesouro(ana, camp, op="give_item", id=item["id"], to=kian).get_json()["treasure"]
    assert state["items"] == []  # acabou: sai da lista


def test_tesouro_nao_mexe_nas_fichas(mesa, app):
    from app.extensions import db
    from app.models import Character
    camp, kian, lia = mesa_completa(mesa)
    with app.app_context():
        before = dict(db.session.get(Character, kian).data)
    ana = mesa.user("ana")
    tesouro(ana, camp, op="coins", deltas={"po": 10})
    tesouro(ana, camp, op="split", characters=[kian, lia])
    with app.app_context():
        assert db.session.get(Character, kian).data == before


def test_divisao_de_moedas_deixa_a_sobra(mesa):
    camp, kian, lia = mesa_completa(mesa)
    ana = mesa.user("ana")
    tesouro(ana, camp, op="coins", deltas={"po": 11, "pp": 1})
    state = tesouro(ana, camp, op="split", characters=[kian, lia]).get_json()["treasure"]
    coins = {c["key"]: c["amount"] for c in state["coins"]}
    assert coins["po"] == 1 and coins["pp"] == 1  # 11 → 5 cada, sobra 1; 1 PP não divide
    text = state["log"][0]["text"]
    assert "Kian" in text and "Lia" in text and "5 PO para cada um" in text and "sobrou" in text

    assert tesouro(ana, camp, op="split", characters=[]).status_code == 400
    assert tesouro(ana, camp, op="split", characters=[kian, lia]).status_code == 400  # 1 PO p/ 2
    one = tesouro(ana, camp, op="split", characters=[kian]).get_json()["treasure"]
    assert {c["key"]: c["amount"] for c in one["coins"]}["po"] == 0


def test_tesouro_e_da_mesa(mesa):
    camp, *_ = mesa_completa(mesa)
    assert mesa.user("intruso").get("/campanhas/%d/tesouro" % camp).status_code == 403
    assert tesouro(mesa.user("intruso"), camp, op="coins", deltas={"po": 1}).status_code == 403
    page = mesa.user("bia").get("/campanhas/%d/tesouro" % camp)
    assert page.status_code == 200 and b"data-treasure" in page.data


def test_tesouro_sem_perder_mudancas_simultaneas(mesa, app):
    camp, *_ = mesa_completa(mesa)
    clients = []
    for _ in range(4):
        client = app.test_client()
        client.post("/entrar", data={"identifier": "ana", "password": "segredo123"})
        clients.append(client)
    errors = []

    def depositar(client):
        response = tesouro(client, camp, op="coins", deltas={"po": 10})
        if response.status_code != 200:
            errors.append(response.status_code)

    threads = [threading.Thread(target=depositar, args=(c,)) for c in clients]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    state = mesa.user("ana").get("/campanhas/%d/ao-vivo?s=treasure::" % camp).get_json()
    coins = {c["key"]: c["amount"] for c in state["sections"]["treasure:"]["data"]["coins"]}
    assert coins["po"] == 40


# ------------------------------------------------------------ calendário
def test_calendario_conversoes():
    cal = worldcal.from_preset("gregoriano", "DR", 1492)
    assert worldcal.format_date(cal, cal["today"]) == "1 de Janeiro de 1492 DR"
    ordinal = worldcal.to_ordinal(cal, 1492, 3, 1)
    assert worldcal.from_ordinal(cal, ordinal) == (1492, 3, 1)
    assert worldcal.from_ordinal(cal, ordinal - 1) == (1492, 2, 28)  # sem bissexto
    assert worldcal.from_ordinal(cal, worldcal.to_ordinal(cal, 1, 12, 31) + 1) == (2, 1, 1)
    for bad in ((1492, 2, 29), (1492, 13, 1), (0, 1, 1)):
        try:
            worldcal.to_ordinal(cal, *bad)
        except worldcal.CalendarError:
            continue
        raise AssertionError("aceitou %r" % (bad,))
    grid = worldcal.month_grid(cal, 1492, 1)
    assert all(len(week) == 7 for week in grid)
    assert sum(1 for week in grid for cell in week if cell) == 31


def test_calendario_personalizado():
    months = worldcal.parse_months("Martelo: 30\nIntervalo: 1\n\nAlturiak: 30")
    assert [m["days"] for m in months] == [30, 1, 30]
    for bad in ("Martelo", "Martelo: 0", ": 30", ""):
        try:
            worldcal.parse_months(bad)
        except worldcal.CalendarError:
            continue
        raise AssertionError("aceitou %r" % bad)


def test_calendario_na_campanha(mesa, app):
    camp, *_ = mesa_completa(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    url = "/campanhas/%d/calendario" % camp
    assert b"ainda n" in ana.get(url).data  # "ainda não configurou"
    assert ana.post(url, data={"action": "setup", "preset": "gregoriano"}).status_code == 403

    mestre.post(url, data={"action": "setup", "preset": "personalizado", "era": "DR", "year": "1492",
                           "months": "Martelo: 30\nAlturiak: 30", "weekdays": "Um, Dois, Três"})
    mestre.post(url, data={"action": "advance", "days": "31"})
    with app.app_context():
        from app.extensions import db
        cal = worldcal.normalize(db.session.get(Campaign, camp).calendar)
    assert worldcal.format_date(cal, cal["today"]) == "2 de Alturiak de 1492 DR"

    # Acontecimento datado aparece na folhinha e na visão geral.
    mestre.post("/campanhas/%d/linha-do-tempo" % camp, data={
        "title": "Queda da torre", "world_day": "2", "world_month": "2", "world_year": "1492"})
    page = ana.get(url + "?ano=1492&mes=2").get_data(as_text=True)
    assert "Queda da torre" in page and "is-today" in page
    assert "2 de Alturiak de 1492 DR" in ana.get("/campanhas/%d" % camp).get_data(as_text=True)
    tl = ana.get("/campanhas/%d/linha-do-tempo" % camp).get_data(as_text=True)
    assert "📅 2 de Alturiak de 1492 DR" in tl

    bad = mestre.post("/campanhas/%d/linha-do-tempo" % camp, data={
        "title": "Impossível", "world_day": "40", "world_month": "1", "world_year": "1492"},
        follow_redirects=True)
    assert "Martelo tem 30 dias" in bad.get_data(as_text=True)


def test_sessao_com_data_no_mundo(mesa, app):
    from app.models import GameSession
    camp, *_ = mesa_completa(mesa)
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/calendario" % camp, data={"action": "setup", "preset": "gregoriano",
                                                        "year": "1200"})
    mestre.post("/campanhas/%d/sessoes/nova" % camp, data={"title": "Chegada"})
    with app.app_context():
        session = GameSession.query.filter_by(campaign_id=camp).one()
        sid = session.id
    mestre.post("/campanhas/%d/sessoes/%d" % (camp, sid), data={
        "title": "Chegada", "world_day": "10", "world_month": "1", "world_year": "1200"})
    page = mestre.get("/campanhas/%d/calendario?ano=1200&mes=1" % camp).get_data(as_text=True)
    assert "Sessão 1 · Chegada" in page
