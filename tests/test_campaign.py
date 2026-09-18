# -*- coding: utf-8 -*-
"""Campanha, sessões, presença, anotações (com revelação) e permissões."""
from app.models import Campaign, GameSession, Note, SessionAttendance, User


def table(mesa, *players):
    camp, code = mesa.campaign("mestre")
    for player in players:
        mesa.join(player, code)
    return camp, code


def test_criar_campanha_e_entrar_por_codigo(mesa):
    camp, code = table(mesa)
    assert len(code) == 6
    client = mesa.user("ana")
    assert client.get("/campanhas/%d" % camp).status_code == 403
    mesa.join("ana", code)
    assert client.get("/campanhas/%d" % camp).status_code == 200


def test_permissoes_do_jogador(mesa):
    camp, _ = table(mesa, "ana")
    mestre_cid = mesa.character("mestre", camp, name="Do mestre")
    client = mesa.user("ana")
    assert client.post("/campanhas/%d/sessoes/nova" % camp, data={"title": "x"}).status_code == 403
    assert client.post("/campanhas/%d/excluir" % camp).status_code == 403
    assert client.get("/fichas/%d" % mestre_cid).status_code == 200
    assert client.post("/fichas/%d" % mestre_cid, data={"attr__agi": "5"}).status_code == 403


def test_sessao_com_horario_cenas_e_checklist(mesa):
    camp, _ = table(mesa)
    client = mesa.user("mestre")
    client.post("/campanhas/%d/sessoes/nova" % camp,
                data={"title": "A descida", "scheduled_for": "2026-10-01", "start_time": "19:30"})
    session = mesa.get(GameSession, 1)
    assert session.start_time == "19:30"

    client.post("/campanhas/%d/sessoes/1" % camp, data={
        "title": "A descida", "number": "1", "scheduled_for": "2026-10-01", "start_time": "25:99",
        "status": "planejada", "plan": "# Segredo\nO padre mente", "synopsis": "Vocês chegam",
        "beats": "Chegada\nInterrogatório\nEmboscada"})
    session = mesa.get(GameSession, 1)
    assert session.start_time is None                 # horário inválido é descartado
    assert len(session.beats) == 3

    toggle = client.post("/campanhas/%d/sessoes/1/cena" % camp, json={"index": 1})
    assert toggle.get_json() == {"ok": True, "done": True, "progress": 33}


def test_jogador_ve_sinopse_mas_nao_o_roteiro(mesa):
    camp, _ = table(mesa, "ana")
    client = mesa.user("mestre")
    client.post("/campanhas/%d/sessoes/nova" % camp, data={"title": "S"})
    client.post("/campanhas/%d/sessoes/1" % camp, data={"title": "S", "plan": "O padre mente",
                                                         "synopsis": "Vocês chegam à vila"})
    page = mesa.user("ana").get("/campanhas/%d/sessoes/1" % camp)
    assert "chegam à vila".encode() in page.data and b"padre mente" not in page.data


def test_confirmacao_de_presenca(mesa):
    camp, _ = table(mesa, "ana", "bruno")
    mesa.user("mestre").post("/campanhas/%d/sessoes/nova" % camp, data={"title": "S"})
    ana = mesa.user("ana")
    ana.post("/campanhas/%d/sessoes/1/presenca" % camp, data={"status": "talvez", "comment": "chego 20h"})
    ana.post("/campanhas/%d/sessoes/1/presenca" % camp, data={"status": "vou", "comment": "chego 20h"})
    mesa.user("bruno").post("/campanhas/%d/sessoes/1/presenca" % camp, data={"status": "nao"})
    invalida = mesa.user("bruno").post("/campanhas/%d/sessoes/1/presenca" % camp,
                                       data={"status": "quem-sabe"}, follow_redirects=True)
    assert "Escolha uma resposta".encode() in invalida.data

    with mesa.app.app_context():
        answers = {a.user.username: a.status for a in SessionAttendance.query.all()}
    assert answers == {"ana": "vou", "bruno": "nao"}     # atualiza, não duplica

    page = mesa.user("mestre").get("/campanhas/%d/sessoes/1" % camp)
    assert "1 de 2 confirmaram".encode() in page.data and "chego 20h".encode() in page.data

    lista = mesa.user("mestre").get("/campanhas/%d/sessoes" % camp)
    assert "1/2 vêm".encode() in lista.data


def test_anotacao_secreta_nao_vaza(mesa):
    camp, _ = table(mesa, "ana")
    mesa.user("mestre").post("/campanhas/%d/anotacoes/nova" % camp, data={
        "title": "O padre", "body": "**mente**", "visibility": "mestre", "pinned": "on"})
    ana = mesa.user("ana")
    assert "O padre".encode() not in ana.get("/campanhas/%d/anotacoes" % camp).data
    assert "O padre".encode() not in ana.get("/campanhas/%d" % camp).data      # nem nas fixadas
    assert ana.get("/campanhas/%d/anotacoes/1/editar" % camp).status_code == 404
    assert b"<strong>mente</strong>" in mesa.user("mestre").get("/campanhas/%d/anotacoes" % camp).data


def test_revelar_para_jogadores_escolhidos(mesa):
    camp, _ = table(mesa, "ana", "bruno")
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/anotacoes/nova" % camp, data={
        "title": "Carta rasgada", "body": "pista", "visibility": "mestre"})
    with mesa.app.app_context():
        ana_id = User.query.filter_by(username="ana").one().id

    mestre.post("/campanhas/%d/anotacoes/1/revelar" % camp,
                data={"target": "jogadores", "recipients": [str(ana_id)]})
    note = mesa.get(Note, 1)
    assert note.visibility == "jogadores" and note.revealed_at is not None

    ana = mesa.user("ana")
    lista = ana.get("/campanhas/%d/anotacoes" % camp)
    assert "Carta rasgada".encode() in lista.data and "revelada agora".encode() in lista.data
    assert "Revelado para você".encode() in ana.get("/campanhas/%d" % camp).data
    assert ana.get("/campanhas/%d/anotacoes/1/editar" % camp).status_code == 200
    assert ana.post("/campanhas/%d/anotacoes/1/editar" % camp, data={"title": "hack"}).status_code == 403

    bruno = mesa.user("bruno")
    assert "Carta rasgada".encode() not in bruno.get("/campanhas/%d/anotacoes" % camp).data
    assert bruno.get("/campanhas/%d/anotacoes/1/editar" % camp).status_code == 404


def test_destinatario_nao_ve_quem_mais_recebeu(mesa):
    camp, _ = table(mesa, "ana", "bruno")
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/anotacoes/nova" % camp, data={
        "title": "Segredo", "body": "x", "visibility": "jogadores", "recipients": ["2", "3"]})
    lista = mesa.user("ana").get("/campanhas/%d/anotacoes" % camp)
    assert b"bruno" not in lista.data


def test_revelacao_ignora_quem_nao_e_da_mesa(mesa):
    camp, _ = table(mesa, "ana")
    mesa.user("intruso")
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/anotacoes/nova" % camp, data={
        "title": "Só pra intruso", "body": "x", "visibility": "jogadores", "recipients": ["3"]},
        follow_redirects=True)
    note = mesa.get(Note, 1)
    assert note.visibility == "mestre" and not note.recipients


def test_jogador_nao_cria_anotacao_secreta(mesa):
    camp, _ = table(mesa, "ana")
    mesa.user("ana").post("/campanhas/%d/anotacoes/nova" % camp,
                          data={"title": "Minha", "body": "x", "visibility": "mestre"})
    assert mesa.get(Note, 1).visibility == "mesa"


def test_linha_do_tempo(mesa):
    camp, _ = table(mesa)
    client = mesa.user("mestre")
    client.post("/campanhas/%d/linha-do-tempo" % camp, data={"title": "A vila queimou", "label": "3º dia"})
    assert "A vila queimou".encode() in client.get("/campanhas/%d/linha-do-tempo" % camp).data


def test_excluir_campanha_apaga_tudo(mesa):
    camp, _ = table(mesa, "ana")
    mesa.character("ana", camp)
    client = mesa.user("mestre")
    client.post("/campanhas/%d/sessoes/nova" % camp, data={"title": "S"})
    client.post("/campanhas/%d/excluir" % camp)
    from app.extensions import db
    from app.models import Character
    with mesa.app.app_context():
        assert db.session.get(Campaign, camp) is None
        assert Character.query.count() == 0 and GameSession.query.count() == 0
