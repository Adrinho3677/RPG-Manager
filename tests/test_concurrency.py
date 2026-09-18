# -*- coding: utf-8 -*-
"""Edição simultânea: versão da ficha e salvamento automático."""
import json


def setup_table(mesa):
    camp, code = mesa.campaign("mestre")
    mesa.join("ana", code)
    cid = mesa.character("ana", camp)
    return camp, cid


def test_salvamento_automatico_so_mexe_nos_campos_enviados(mesa):
    """Regressão: salvar só o PV atual apagava o máximo e o temporário."""
    _, cid = setup_table(mesa)
    mesa.user("ana").post("/fichas/%d" % cid, data={"bar__pv__current": "12", "bar__pv__max": "30",
                                                    "bar__pv__temp": "3", "skill__luta__train": "5",
                                                    "skill__luta__other": "2"})
    response = mesa.autosave("ana", cid, version="2", bar__pv__current="7", skill__luta__other="4")
    assert response.status_code == 200
    data = mesa.sheet(cid).data
    assert data["bars"]["pv"] == {"current": 7, "max": 30, "temp": 3}
    assert data["skills"]["luta"]["train"] == 5 and data["skills"]["luta"]["other"] == 4


def test_mestre_e_jogador_editando_partes_diferentes_nao_se_apagam(mesa):
    _, cid = setup_table(mesa)
    # os dois abriram a ficha na versão 1
    mestre = mesa.autosave("mestre", cid, version="1", bar__pv__current="4")
    jogador = mesa.autosave("ana", cid, version="1",
                            inventory=json.dumps([{"name": "Pé de cabra", "qty": 1}]))
    assert mestre.get_json()["stale"] is False
    assert jogador.get_json()["stale"] is True          # a tela dela estava velha…
    data = mesa.sheet(cid).data
    assert data["bars"]["pv"]["current"] == 4           # …mas nada se perdeu
    assert data["inventory"][0]["name"] == "Pé de cabra"
    assert mesa.sheet(cid).version == 3


def test_envio_completo_com_versao_velha_e_recusado(mesa):
    _, cid = setup_table(mesa)
    mesa.autosave("mestre", cid, version="1", bar__pv__current="4")     # versão vira 2
    response = mesa.user("ana").post("/fichas/%d" % cid, data={
        "version": "1", "__action": "rest:long", "bar__pv__current": "20", "bar__pv__max": "20"},
        follow_redirects=True)
    assert "foi alterada por outra pessoa".encode() in response.data
    sheet = mesa.sheet(cid)
    assert sheet.data["bars"]["pv"]["current"] == 4 and sheet.version == 2


def test_estado_da_ficha_informa_a_versao(mesa):
    _, cid = setup_table(mesa)
    mesa.autosave("mestre", cid, version="1", bar__pv__current="9")
    state = mesa.user("ana").get("/fichas/%d/estado" % cid).get_json()
    assert state["version"] == 2 and state["bars"]["pv"]["current"] == 9


def test_resposta_do_autosave_traz_maximo_calculado(mesa):
    cid = mesa.character("ana", slug="generico", name="G")
    data = mesa.autosave("ana", cid, version="1", attr__corpo="5").get_json()
    assert data["bars"]["pv"]["max"] == 35 and data["bars"]["pv"]["auto"] is True


def test_xp_do_mestre_conta_como_mudanca_na_ficha(mesa):
    camp, cid = setup_table(mesa)
    client = mesa.user("mestre")
    client.post("/campanhas/%d/sessoes/nova" % camp, data={"title": "S1"})
    client.post("/campanhas/%d/sessoes/1/xp" % camp, data={"amount": "100"})
    assert mesa.sheet(cid).version == 2
    response = mesa.user("ana").post("/fichas/%d" % cid, data={"version": "1", "xp": "0"},
                                     follow_redirects=True)
    assert "foi alterada por outra pessoa".encode() in response.data
    assert mesa.sheet(cid).data["xp"] == 100


def test_quem_nao_edita_nao_salva(mesa):
    camp, code = mesa.campaign("mestre")
    mesa.join("ana", code)
    mesa.join("bruno", code)
    cid = mesa.character("ana", camp)
    assert mesa.autosave("bruno", cid, version="1", xp="999").status_code == 403
