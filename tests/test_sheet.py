# -*- coding: utf-8 -*-
"""Ficha: campos, listas, carga, descanso, XP, fórmulas, impressão."""
import json

from app.models import Character


def test_ficha_nova_tem_as_barras_do_sistema(mesa):
    cid = mesa.character("ana")
    sheet = mesa.sheet(cid)
    assert set(sheet.data["bars"]) == {"pv", "pe", "san"}
    assert sheet.version == 1


def test_abrir_ficha_mostra_abas_e_campos(mesa):
    cid = mesa.character("ana")
    page = mesa.user("ana").get("/fichas/%d" % cid)
    assert page.status_code == 200
    for text in ("data-tab-button=\"pericias\"", "Agilidade", "Sanidade", "Ocultismo", "novalidate"):
        assert text.encode() in page.data


def test_salvar_formulario_completo(mesa):
    cid = mesa.character("ana")
    response = mesa.user("ana").post("/fichas/%d" % cid, data={
        "version": "1",
        "attr__agi": "3", "bar__pv__current": "12", "bar__pv__max": "20", "bar__pv__temp": "2",
        "skill__ocultismo__train": "10", "skill__ocultismo__other": "2", "meta__classe": "Ocultista",
        "inventory": json.dumps([{"name": "Lanterna", "qty": 1, "weight": "0,5", "category": "xyz"}]),
        "attacks": json.dumps([{"name": "Tiro", "test": "pontaria", "bonus": 2, "damage": "2d8+3"}]),
        "spells": json.dumps([{"name": "Sopro", "level": 1, "prepared": True}]),
        "conditions": json.dumps([{"name": "Sangrando", "rounds": 3}]),
        "money__dinheiro": "350", "xp": "-5", "notes": "anotação",
    })
    assert response.status_code == 302
    data = mesa.sheet(cid).data
    assert data["attributes"]["agi"] == 3
    assert data["bars"]["pv"] == {"current": 12, "max": 20, "temp": 2}
    assert data["skills"]["ocultismo"]["train"] == 10
    assert data["inventory"][0]["weight"] == 0.5          # vírgula aceita
    assert data["inventory"][0]["category"] == "geral"    # categoria inválida corrigida
    assert data["attacks"][0]["damage"] == "2d8+3"
    assert data["spells"][0]["prepared"] is True
    assert data["money"]["dinheiro"] == 350
    assert data["xp"] == 0                                 # não fica negativo
    assert mesa.sheet(cid).version == 2


def test_atual_nao_passa_do_maximo(mesa):
    cid = mesa.character("ana")
    mesa.user("ana").post("/fichas/%d" % cid, data={"bar__pv__current": "999", "bar__pv__max": "20"})
    assert mesa.sheet(cid).data["bars"]["pv"]["current"] == 20


def test_campos_criados_na_ficha(mesa):
    client = mesa.user("ana")
    cid = mesa.character("ana")
    url = "/fichas/%d" % cid
    client.post(url, data={"__action": "add_attribute", "new_attr_name": "Sorte", "new_attr_value": "2",
                           "new_attr_max": "5"})
    client.post(url, data={"__action": "add_bar", "new_bar_name": "Munição", "new_bar_max": "6"})
    client.post(url, data={"__action": "add_skill", "new_skill_name": "Gastronomia", "new_skill_attr": "int"})
    client.post(url, data={"__action": "add_meta", "new_meta_name": "Fraqueza"})
    custom = mesa.sheet(cid).data["custom"]
    assert custom["attributes"][0]["key"] == "sorte"
    assert custom["bars"][0]["default_max"] == 6
    assert custom["skills"][0]["name"] == "Gastronomia"
    assert custom["meta_fields"][0]["key"] == "fraqueza"

    client.post(url, data={"__action": "remove:attribute:sorte"})
    data = mesa.sheet(cid).data
    assert not data["custom"]["attributes"] and "sorte" not in data["attributes"]


def test_carga_por_espacos_e_sobrecarga(mesa):
    from app.sheet import build
    cid = mesa.character("ana")
    client = mesa.user("ana")
    client.post("/fichas/%d" % cid, data={
        "attr__for": "3",
        "inventory": json.dumps([{"name": "Rifle", "qty": 1, "weight": 3},
                                 {"name": "Ração", "qty": 4, "weight": 0.5}]),
    })
    with mesa.app.app_context():
        from app.extensions import db
        load = build(db.session.get(Character, cid))["load"]
        assert load["capacity"] == 17 and load["used"] == 5 and load["state"] == "ok"

    client.post("/fichas/%d" % cid, data={"attr__for": "1",
                                          "inventory": json.dumps([{"name": "Bigorna", "qty": 3, "weight": 10}])})
    with mesa.app.app_context():
        from app.extensions import db
        assert build(db.session.get(Character, cid))["load"]["state"] == "over"


def test_descanso_segue_a_regra_de_cada_barra(mesa):
    cid = mesa.character("ana")
    client = mesa.user("ana")
    url = "/fichas/%d" % cid
    client.post(url, data={"bar__pv__current": "5", "bar__pv__max": "20", "bar__pv__temp": "4",
                           "bar__pe__current": "1", "bar__pe__max": "10",
                           "bar__san__current": "6", "bar__san__max": "12"})

    client.post(url, data={"__action": "rest:short"})
    bars = mesa.sheet(cid).data["bars"]
    assert bars["pv"]["current"] == 5 and bars["pv"]["temp"] == 4

    response = client.post(url, data={"__action": "rest:long"}, follow_redirects=True)
    bars = mesa.sheet(cid).data["bars"]
    assert bars["pv"] == {"current": 20, "max": 20, "temp": 0}
    assert bars["pe"]["current"] == 10
    assert bars["san"]["current"] == 6                 # sanidade não volta
    assert "PV +15".encode() in response.data


def test_descanso_aplica_sobre_o_que_foi_enviado_junto(mesa):
    cid = mesa.character("ana")
    mesa.user("ana").post("/fichas/%d" % cid, data={
        "__action": "rest:long", "meta__classe": "Combatente", "bar__pv__current": "2"})
    data = mesa.sheet(cid).data
    assert data["meta"]["classe"] == "Combatente" and data["bars"]["pv"]["current"] == 20


def test_xp_soma_e_registra(mesa):
    cid = mesa.character("ana")
    client = mesa.user("ana")
    client.post("/fichas/%d" % cid, data={"__action": "add_xp", "new_xp_amount": "250",
                                          "new_xp_note": "Derrotaram o Ghoul"})
    client.post("/fichas/%d" % cid, data={"__action": "add_xp", "new_xp_amount": "100",
                                          "new_xp_note": "Enigma"})
    data = mesa.sheet(cid).data
    assert data["xp"] == 350
    assert [e["name"] for e in data["progress"]] == ["Derrotaram o Ghoul", "Enigma"]


def test_ordem_do_log_sobrevive_a_um_salvamento(mesa):
    """Regressão: a lista era exibida invertida e o JS regravava invertida."""
    from app.sheet import build
    cid = mesa.character("ana")
    client = mesa.user("ana")
    for note in ("primeiro", "segundo", "terceiro"):
        client.post("/fichas/%d" % cid, data={"__action": "add_xp", "new_xp_amount": "1", "new_xp_note": note})
    with mesa.app.app_context():
        from app.extensions import db
        shown = build(db.session.get(Character, cid))["progress"]
    client.post("/fichas/%d" % cid, data={"progress": json.dumps(shown)})
    assert [e["name"] for e in mesa.sheet(cid).data["progress"]] == ["primeiro", "segundo", "terceiro"]


def test_formula_de_maximo_acompanha_o_atributo(mesa):
    """Sistema Genérico: PV = 10 + COR * 5."""
    cid = mesa.character("ana", slug="generico", name="Fórmula")
    data = mesa.sheet(cid).data
    assert data["bars"]["pv"]["max"] == 20 and data["bars"]["pv"]["current"] == 20  # COR 2

    client = mesa.user("ana")
    client.post("/fichas/%d" % cid, data={"attr__corpo": "4"})
    assert mesa.sheet(cid).data["bars"]["pv"]["max"] == 30

    client.post("/fichas/%d" % cid, data={"bar__pv__current": "25"})
    client.post("/fichas/%d" % cid, data={"attr__corpo": "1"})     # máximo cai para 15
    bars = mesa.sheet(cid).data["bars"]
    assert bars["pv"] == {"current": 15, "max": 15, "temp": 0}

    client.post("/fichas/%d" % cid, data={"bar__pv__max": "999"})  # máximo com fórmula ignora o digitado
    assert mesa.sheet(cid).data["bars"]["pv"]["max"] == 15


def test_barra_criada_na_ficha_com_formula(mesa):
    cid = mesa.character("ana")
    client = mesa.user("ana")
    client.post("/fichas/%d" % cid, data={"attr__vig": "3"})
    client.post("/fichas/%d" % cid, data={"__action": "add_bar", "new_bar_name": "Fôlego",
                                          "new_bar_max_formula": "2 + VIG * 2"})
    assert mesa.sheet(cid).data["bars"]["folego"] == {"current": 8, "max": 8, "temp": 0}

    ruim = client.post("/fichas/%d" % cid, data={"__action": "add_bar", "new_bar_name": "Quebrada",
                                                 "new_bar_max_formula": "VIG +"}, follow_redirects=True)
    assert "a fórmula não funcionou".encode() in ruim.data


def test_ficha_no_formato_antigo_abre_e_salva(mesa):
    from app.extensions import db
    cid = mesa.character("ana")
    with mesa.app.app_context():
        character = db.session.get(Character, cid)
        character.data = {"attributes": {"agi": 2}, "inventory": [{"name": "Corda", "qty": 1}], "notes": "velha"}
        db.session.commit()
    client = mesa.user("ana")
    assert client.get("/fichas/%d" % cid).status_code == 200
    client.post("/fichas/%d" % cid, data={"notes": "atualizada"})
    data = mesa.sheet(cid).data
    assert data["notes"] == "atualizada" and data["inventory"][0]["name"] == "Corda"
    assert data["attacks"] == [] and data["progress"] == []


def test_pagina_de_impressao(mesa):
    cid = mesa.character("ana")
    page = mesa.user("ana").get("/fichas/%d/imprimir" % cid)
    assert page.status_code == 200
    assert b"Salvar como PDF" in page.data and b"print.css" in page.data and "Ocultismo".encode() in page.data
