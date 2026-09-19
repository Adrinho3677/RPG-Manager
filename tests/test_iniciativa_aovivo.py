# -*- coding: utf-8 -*-
"""Rodadas, iniciativa automática e a consulta única ao vivo."""
from app.models import Encounter, RollLog


def combate(mesa, slug="dnd-5e"):
    camp, code = mesa.campaign("mestre", slug=slug)
    mesa.join("ana", code)
    kian = mesa.character("ana", camp, name="Kian")
    ghoul = mesa.character("mestre", camp, name="Ghoul", kind="criatura")
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/combate/novo" % camp, data={"name": "Briga"})
    base = "/campanhas/%d/combate/1" % camp
    mestre.post(base + "/adicionar", json={"party": True})
    mestre.post(base + "/adicionar", json={"character_id": ghoul, "quantity": 2})
    return camp, base, kian, ghoul


def test_avulso_sem_nome_nao_some_nem_desloca_o_turno(mesa):
    camp, base, *_ = combate(mesa)
    mestre = mesa.user("mestre")
    state = mestre.get(base + "/estado").get_json()
    state["combatants"].append({"name": "", "init": 0, "hp": 5, "hp_max": 5, "kind": "criatura"})
    state["turn_index"] = 2
    saved = mestre.post(base + "/salvar", json=state).get_json()
    assert len(saved["combatants"]) == 4
    assert saved["combatants"][saved["turn_index"]]["name"] == state["combatants"][2]["name"]
    assert any(c["name"].startswith("Combatente") for c in saved["combatants"])


def test_rodada_avanca_mesmo_sem_combatentes(mesa):
    camp, code = mesa.campaign("mestre")
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/combate/novo" % camp, data={"name": "Vazio"})
    base = "/campanhas/%d/combate/1" % camp
    saved = mestre.post(base + "/salvar", json={"combatants": [], "round_number": 2,
                                                "turn_index": 0}).get_json()
    assert saved["round_number"] == 2


def test_iniciativa_rola_pela_regra_do_sistema(mesa, app):
    camp, base, kian, _ = combate(mesa)
    mestre = mesa.user("mestre")
    state = mestre.post(base + "/iniciativa", json={"scope": "todos"}).get_json()
    inits = [c["init"] for c in state["combatants"]]
    assert inits == sorted(inits, reverse=True)
    assert all(1 <= i <= 20 for i in inits)  # DES 10 em D&D: 1d20 + 0
    assert state["turn_index"] == 0
    assert "Iniciativa rolada" in state["messages"][0]

    with app.app_context():
        logs = RollLog.query.filter_by(label="Iniciativa").all()
        publico = [l for l in logs if not l.secret]
        secreto = [l for l in logs if l.secret]
        assert len(publico) == 1 and "Kian" in publico[0].detail
        assert len(secreto) == 1 and "Ghoul" in secreto[0].detail and "Kian" not in secreto[0].detail


def test_iniciativa_so_do_grupo_mantem_o_resto(mesa):
    camp, base, *_ = combate(mesa)
    mestre = mesa.user("mestre")
    state = mestre.get(base + "/estado").get_json()
    for c in state["combatants"]:
        c["init"] = 50 if c["kind"] != "pj" else 0
    mestre.post(base + "/salvar", json=state)
    rolled = mestre.post(base + "/iniciativa", json={"scope": "grupo"}).get_json()
    ghouls = [c["init"] for c in rolled["combatants"] if c["kind"] != "pj"]
    assert ghouls == [50, 50]  # o mestre tinha digitado; ficou


def test_iniciativa_sem_rolar_usa_o_valor(mesa):
    camp, base, *_ = combate(mesa, slug="chamado-de-cthulhu")
    state = mesa.user("mestre").post(base + "/iniciativa", json={}).get_json()
    assert {c["init"] for c in state["combatants"]} == {50}  # DES padrão 50, sem dado


def test_iniciativa_ordem_paranormal_usa_a_pericia(mesa, app):
    from app.extensions import db
    from app.models import Character
    camp, base, kian, _ = combate(mesa, slug="ordem-paranormal")
    with app.app_context():
        ch = db.session.get(Character, kian)
        data = dict(ch.data)
        data["skills"] = dict(data.get("skills") or {}, iniciativa={"train": 15, "other": 0})
        ch.data = data
        db.session.commit()
    state = mesa.user("mestre").post(base + "/iniciativa", json={"scope": "grupo"}).get_json()
    kian_init = [c["init"] for c in state["combatants"] if c["name"] == "Kian"][0]
    assert 16 <= kian_init <= 35  # 1d20 (AGI 1) + 15 de treino


def test_jogador_nao_rola_iniciativa(mesa):
    camp, base, *_ = combate(mesa)
    assert mesa.user("ana").post(base + "/iniciativa", json={}).status_code == 403


def test_editor_de_sistema_guarda_a_iniciativa(mesa, app):
    from app.extensions import db
    from app.models import GameSystem
    import json
    client = mesa.user("mestre")
    response = client.post("/sistemas/%d/duplicar" % mesa.system_id("dnd-5e"))
    system_id = int(response.headers["Location"].rstrip("/").split("/")[-2])
    with app.app_context():
        data = dict(db.session.get(GameSystem, system_id).data)
    data["initiative"] = {"source": "formula", "formula": "DES + 2", "roll": False}
    client.post("/sistemas/%d/editar" % system_id, data={"name": "Meu D&D", "payload": json.dumps(data)})
    with app.app_context():
        spec = db.session.get(GameSystem, system_id).data["initiative"]
    assert spec == {"source": "formula", "formula": "DES + 2", "roll": False}


# ------------------------------------------------------------ consulta única
def test_consulta_unica_devolve_as_secoes(mesa):
    camp, base, kian, _ = combate(mesa)
    ana = mesa.user("ana")
    url = "/campanhas/%d/ao-vivo?s=rolls:0:,enc:1:,board:1:,sheet:%d:,clocks::,spot::,treasure::" % (camp, kian)
    data = ana.get(url).get_json()["sections"]
    assert set(data) == {"rolls:0", "enc:1", "board:1", "sheet:%d" % kian, "clocks:",
                         "spot:", "treasure:"}
    assert data["spot:"] == {"same": True}  # nada sendo mostrado
    enc = data["enc:1"]
    assert "hp" not in [c for c in enc["data"]["combatants"] if c["kind"] != "pj"][0]

    # Pedindo de novo com as marcas recebidas: nada mudou.
    marks = {k: v.get("mark", "") for k, v in data.items()}
    again = ana.get("/campanhas/%d/ao-vivo?s=enc:1:%s,board:1:%s,sheet:%d:%s" % (
        camp, marks["enc:1"], marks["board:1"], kian, marks["sheet:%d" % kian])).get_json()["sections"]
    assert all(v == {"same": True} for v in again.values())


def test_consulta_unica_respeita_permissoes(mesa):
    camp, base, *_ = combate(mesa)
    assert mesa.user("intruso").get("/campanhas/%d/ao-vivo?s=rolls:0:" % camp).status_code == 403
    outra, _ = mesa.campaign("outro", name="Outra")
    # combate de outra campanha não vaza pela minha
    assert mesa.user("mestre").get("/campanhas/%d/ao-vivo?s=enc:999:" % camp).status_code == 404
