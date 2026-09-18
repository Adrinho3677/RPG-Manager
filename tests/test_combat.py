# -*- coding: utf-8 -*-
"""Combate ligado às fichas, bestiário e o que jogadores podem ver."""
import json

from app.models import Encounter


def arena(mesa):
    camp, code = mesa.campaign("mestre")
    mesa.join("ana", code)
    kian = mesa.character("ana", camp, name="Kian")
    ghoul = mesa.character("mestre", camp, name="Ghoul", kind="criatura")
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/combate/novo" % camp, data={"name": "Emboscada"})
    return camp, kian, ghoul, mestre


def urls(camp, eid=1):
    base = "/campanhas/%d/combate/%d" % (camp, eid)
    return base + "/adicionar", base + "/salvar", base + "/estado"


def test_grupo_entra_ligado_a_ficha(mesa):
    camp, kian, _, mestre = arena(mesa)
    add, _, _ = urls(camp)
    state = mestre.post(add, json={"party": True}).get_json()
    assert [c["character_id"] for c in state["combatants"]] == [kian]
    assert state["combatants"][0]["hp"] == 20

    again = mestre.post(add, json={"party": True}).get_json()
    assert len(again["combatants"]) == 1 and again["messages"]


def test_criatura_vira_copias_independentes(mesa):
    camp, _, ghoul, mestre = arena(mesa)
    add, _, _ = urls(camp)
    mestre.post(add, json={"character_id": ghoul, "quantity": 2})
    state = mestre.post(add, json={"character_id": ghoul, "quantity": 1}).get_json()
    names = [c["name"] for c in state["combatants"]]
    assert names == ["Ghoul 1", "Ghoul 2", "Ghoul 3"]
    assert all(c["character_id"] is None for c in state["combatants"])


def test_dano_no_rastreador_vai_para_a_ficha(mesa):
    camp, kian, _, mestre = arena(mesa)
    add, save, _ = urls(camp)
    state = mestre.post(add, json={"party": True}).get_json()
    state["combatants"][0]["hp"] = 13
    result = mestre.post(save, json=state).get_json()
    assert result["combatants"][0]["hp"] == 13
    sheet = mesa.sheet(kian)
    assert sheet.data["bars"]["pv"]["current"] == 13
    assert sheet.version == 2                           # a ficha aberta do jogador vai perceber


def test_rastreador_velho_nao_desfaz_o_que_o_jogador_anotou(mesa):
    camp, kian, _, mestre = arena(mesa)
    add, save, _ = urls(camp)
    state = mestre.post(add, json={"party": True}).get_json()     # carregou PV 20
    mesa.autosave("ana", kian, version="1", bar__pv__current="8")  # jogador anota dano
    state["round_number"] = 1
    result = mestre.post(save, json=state).get_json()              # mestre salva sem mexer no PV
    assert mesa.sheet(kian).data["bars"]["pv"]["current"] == 8
    assert result["combatants"][0]["hp"] == 8


def test_condicoes_perdem_rodadas_e_acabam(mesa):
    camp, kian, _, mestre = arena(mesa)
    add, save, _ = urls(camp)
    mesa.user("ana").post("/fichas/%d" % kian, data={"conditions": json.dumps([
        {"name": "Sangrando", "rounds": 2}, {"name": "Amaldiçoado", "rounds": 0}])})
    state = mestre.post(add, json={"party": True}).get_json()

    state["round_number"] = 2
    state = mestre.post(save, json=state).get_json()
    assert {c["name"]: c["rounds"] for c in state["combatants"][0]["conditions"]} == {
        "Sangrando": 1, "Amaldiçoado": 0}

    state["round_number"] = 3
    state = mestre.post(save, json=state).get_json()
    assert [c["name"] for c in state["combatants"][0]["conditions"]] == ["Amaldiçoado"]
    assert any("Sangrando acabou" in m for m in state["messages"])

    state["round_number"] = 2                              # voltar rodada não devolve condição
    state = mestre.post(save, json=state).get_json()
    assert [c["name"] for c in state["combatants"][0]["conditions"]] == ["Amaldiçoado"]


def test_ordenar_por_iniciativa_mantem_a_vez(mesa):
    camp, _, ghoul, mestre = arena(mesa)
    add, save, _ = urls(camp)
    state = mestre.post(add, json={"party": True}).get_json()
    state = mestre.post(add, json={"character_id": ghoul, "quantity": 1}).get_json()
    state["combatants"][0]["init"] = 5    # Kian
    state["combatants"][1]["init"] = 18   # Ghoul 1
    state["turn_index"] = 0               # vez do Kian
    result = mestre.post(save, json=state).get_json()
    assert [c["name"] for c in result["combatants"]] == ["Ghoul 1", "Kian"]
    assert result["combatants"][result["turn_index"]]["name"] == "Kian"


def test_jogador_nao_recebe_pv_nem_notas_de_inimigos(mesa):
    camp, _, ghoul, mestre = arena(mesa)
    add, save, poll = urls(camp)
    state = mestre.post(add, json={"party": True}).get_json()
    state = mestre.post(add, json={"character_id": ghoul}).get_json()
    state["combatants"][1]["notes"] = "foge no turno 3"
    state["combatants"][1]["hp"] = 3
    state["combatants"][1]["hp_max"] = 10
    mestre.post(save, json=state)

    view = mesa.user("ana").get(poll).get_json()
    player_side = {c["name"]: c for c in view["combatants"]}
    assert player_side["Kian"]["hp"] == 20
    enemy = player_side["Ghoul 1"]
    assert "hp" not in enemy and "notes" not in enemy and enemy["health"] == "grave"

    page = mesa.user("ana").get("/campanhas/%d/combate" % camp)
    assert b"foge no turno" not in page.data


def test_jogador_nao_edita_combate(mesa):
    camp, _, _, _ = arena(mesa)
    add, save, _ = urls(camp)
    ana = mesa.user("ana")
    assert ana.post(save, json={"combatants": []}).status_code == 403
    assert ana.post(add, json={"party": True}).status_code == 403


def test_ficha_de_outra_campanha_nao_entra(mesa):
    camp, _, _, mestre = arena(mesa)
    other, _ = mesa.campaign("mestre", name="Outra")
    stranger = mesa.character("mestre", other, name="Estranho", kind="npc")
    add, save, _ = urls(camp)
    assert mestre.post(add, json={"character_id": stranger}).status_code == 404
    state = {"combatants": [{"name": "X", "character_id": stranger, "hp": 1, "hp_loaded": 20}],
             "round_number": 1, "turn_index": 0}
    result = mestre.post(save, json=state).get_json()
    assert result["combatants"][0]["character_id"] is None
    assert mesa.sheet(stranger).data["bars"]["pv"]["current"] == 20
    with mesa.app.app_context():
        assert Encounter.query.count() == 1
