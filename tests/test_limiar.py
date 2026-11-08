# -*- coding: utf-8 -*-
"""Limiar: preset, assistente de criação e conferência da ficha."""
import json

from app import limiar
from app.extensions import db
from app.models import Character


def tessa(**changes):
    """O exemplo de criação do Livro do Jogador: Tessa Oren, Escavadora Decifradora."""
    choices = {
        "version": "0.23", "name": "Tessa Oren", "concept": "Parou de cavar para ler",
        "terra": "cidades_livres", "passado": "escavador", "arquetipo": "decifrador",
        "attributes": {"corpo": 2, "mente": 3, "alma": 2, "poder": 1},
        "skills": ["percepcao", "sobrevivencia", "furtividade", "medicina", "intuicao"],
        "bencaos": ["olhar_atento", "resistente", "passos_leves"], "marcas": ["ferida_antiga"],
        "weapon": "picareta", "armor": "couro",
    }
    choices.update(changes)
    return limiar.clean_choices(choices)


def errors(choices):
    return [p for p in limiar.check_creation(choices) if p["level"] == "erro"]


def test_exemplo_do_livro_passa_e_bate_os_valores():
    choices = tessa()
    assert limiar.check_creation(choices) == []
    # Livro: PV 20, PI 5, Defesa 16, carga 10.
    assert limiar.derived(choices) == {"pv": 20, "pi": 5, "defesa": 16, "armadura": 2, "carga": 10}


def test_atributos_fora_da_regra():
    assert errors(tessa(attributes={"corpo": 4, "mente": 2, "alma": 1, "poder": 1}))
    assert errors(tessa(attributes={"corpo": 3, "mente": 3, "alma": 2, "poder": 1}))  # 9 pontos
    two_zeros = tessa(attributes={"corpo": 3, "mente": 3, "alma": 0, "poder": 0})
    assert any("Só um atributo" in p["msg"] for p in errors(two_zeros))
    # Zerar um atributo devolve o ponto: 0/3/3/2 soma 8 e vale.
    zero = tessa(attributes={"corpo": 3, "mente": 3, "alma": 2, "poder": 0},
                 skills=["percepcao", "sobrevivencia", "furtividade", "medicina", "intuicao"])
    assert not [p for p in errors(zero) if p["step"] == "atributos"]


def test_pericias_contam_mente_e_repetidas():
    # Erudito (História Antiga, Medicina) + Decifrador (Investigação, História Antiga):
    # a repetida vira uma escolha livre a mais. Mente 3 -> 2 + 3 + 1 = 6.
    choices = tessa(passado="erudito")
    picks, fixed = limiar.free_skill_picks(choices)
    assert picks == 6 and fixed == {"historia_antiga", "medicina", "investigacao"}
    choices = tessa(passado="erudito", skills=["percepcao", "sobrevivencia", "furtividade",
                                                 "intuicao", "atletismo", "oficios"])
    assert not [p for p in limiar.check_creation(choices) if p["step"] == "pericias"]
    again = tessa(skills=["atletismo", "percepcao", "sobrevivencia", "furtividade", "medicina"])
    assert any("Já treinada" in p["msg"] for p in errors(again))


def test_orcamento_de_bencaos():
    assert any("orçamento" in p["msg"] for p in errors(tessa(marcas=[])))  # 6 de 4
    four_marcas = tessa(marcas=["desajeitado", "distraido", "voto", "desconfiado"])
    assert any("3 Marcas" in p["msg"] for p in errors(four_marcas))
    leftover = tessa(bencaos=["olhar_atento"])
    assert any("perdidos" in p["msg"] for p in limiar.check_creation(leftover))


def test_v024_afinidade_dons_e_sem_afinidade():
    # Sem afinidade: +3 pontos de Bênção (4 + 2 da Marca + 3 = 9).
    budget, _, bonus = limiar.bencao_budget(tessa(version="0.24"))
    assert (budget, bonus) == (9, 3)
    assert limiar.bencao_budget(tessa(version="0.23"))[0] == 6
    # Canalizador: exatamente duas afinidades, e dons só das escolas dele.
    canal = dict(arquetipo="canalizador", version="0.24", armor="", weapon="punhal",
                 skills=["percepcao", "sobrevivencia", "furtividade", "medicina", "intuicao"])
    one = tessa(afinidades=["tempestade"], dons=["descarga", "chama"], **canal)
    assert any("exatamente duas" in p["msg"] for p in errors(one))
    wrong = tessa(afinidades=["tempestade", "carne"], principal="tempestade",
                  dons=["descarga", "ruido"], **canal)
    assert any("Ruído é da escola Véu" in p["msg"] for p in errors(wrong))
    ok = tessa(afinidades=["tempestade", "carne"], principal="tempestade",
               dons=["descarga", "revigorar"], **canal)
    assert not [p for p in errors(ok) if p["step"] in ("afinidade", "dons")]
    # Na v0.23 não há afinidade, nem Quebra-Pacto.
    assert errors(tessa(afinidades=["pedra"]))
    assert errors(tessa(passado="quebra_pacto"))
    assert not [p for p in errors(tessa(version="0.24", passado="quebra_pacto"))
                if p["step"] == "passado"]


def test_kit_do_arquetipo():
    assert any("armadura" in p["msg"] for p in errors(tessa(armor="cota_malha")))  # média
    vanguarda = tessa(arquetipo="vanguarda", weapon="espada_longa", armor="cota_malha",
                      shield="broquel", skills=["percepcao", "sobrevivencia", "furtividade",
                                                "medicina", "intuicao"])
    assert not [p for p in errors(vanguarda) if p["step"] == "equipamento"]
    assert limiar.derived(vanguarda)["defesa"] == 10 + 2 * 2 + 4 + 2


def test_assistente_cria_a_ficha(mesa):
    client = mesa.user("ana")
    assert b"Novo personagem de Limiar" in client.get("/fichas/nova/limiar").data
    response = client.post("/fichas/nova/limiar", data={"choices": json.dumps(tessa())})
    assert response.status_code == 302
    with mesa.app.app_context():
        character = Character.query.filter_by(name="Tessa Oren").first()
        data = character.data
        assert character.system.slug == "limiar"
    assert data["attributes"] == {"corpo": 2, "mente": 3, "alma": 2, "poder": 1}
    assert data["bars"]["pv"] == {"current": 20, "max": 20, "temp": 0}
    assert data["bars"]["pi"]["max"] == 5
    assert data["bars"]["dissonancia"]["current"] == 0
    assert data["meta"]["defesa"] == "16"
    trained = sorted(k for k, s in data["skills"].items() if s["train"] == 5)
    assert trained == sorted(["atletismo", "oficios", "investigacao", "historia_antiga",
                              "percepcao", "sobrevivencia", "furtividade", "medicina", "intuicao"])
    assert 20 <= data["money"]["dr"] <= 120 and data["money"]["dr"] % 10 == 0
    assert "Dracmas iniciais" in data["progress"][0]["desc"]
    names = [a["name"] for a in data["abilities"]]
    assert "Bênção: Olhar Atento" in names and "Marca: Ferida Antiga" in names
    assert data["attacks"][0]["name"] == "Picareta"
    # Ficha recém-criada passa na conferência.
    page = client.get("/fichas/%d" % character.id)
    assert b"Conferir regras de Limiar" in page.data and b"tudo certo" in page.data


def test_assistente_recusa_criacao_errada(mesa):
    client = mesa.user("ana")
    bad = tessa(attributes={"corpo": 3, "mente": 3, "alma": 3, "poder": 3})
    response = client.post("/fichas/nova/limiar", data={"choices": json.dumps(bad)})
    assert response.status_code == 200 and "Pontos demais".encode() in response.data
    with mesa.app.app_context():
        assert Character.query.filter_by(name="Tessa Oren").count() == 0


def test_conferir_ao_vivo(mesa):
    response = mesa.user("ana").post("/fichas/nova/limiar/conferir", json=tessa(passado="erudito"),
                                     headers={"X-Requested-With": "fetch"})
    body = response.get_json()
    assert body["skill_picks"] == 6 and body["derived"]["pv"] == 20
    assert "historia_antiga" in body["fixed_skills"]


def test_conferencia_da_ficha_em_jogo(mesa):
    client = mesa.user("ana")
    client.post("/fichas/nova/limiar", data={"choices": json.dumps(tessa())})
    with mesa.app.app_context():
        cid = Character.query.filter_by(name="Tessa Oren").first().id
    # Avançado no nível 1, atributo 4 e Defesa errada.
    mesa.autosave("ana", cid, skill__percepcao__train="10", attr__mente="4", meta__defesa="20")
    with mesa.app.app_context():
        msgs = [p["msg"] for p in limiar.check_sheet(db.session.get(Character, cid))]
    assert any("Avançado" in m for m in msgs)
    assert any("Mente está em 4" in m for m in msgs)
    assert any("Defesa 20" in m for m in msgs)
    # Nível 10 com XP suficiente libera o Avançado (e o +1 de atributo do nível 8).
    mesa.autosave("ana", cid, meta__nivel="10", xp="115", meta__defesa="16")
    with mesa.app.app_context():
        character = db.session.get(Character, cid)
        msgs = [p["msg"] for p in limiar.check_sheet(character)]
        assert character.data["bars"]["pv"]["max"] == 10 + 2 * 5 + 3 * 5
    assert not any("Avançado" in m or "Mente está" in m for m in msgs)


def test_ficha_em_branco_de_limiar_comeca_sem_dissonancia(mesa):
    cid = mesa.character("ana", slug="limiar", name="Branca")
    data = mesa.sheet(cid).data
    assert data["bars"]["dissonancia"]["current"] == 0
    assert data["bars"]["consciencia"]["current"] == 0
    page = mesa.user("ana").get("/fichas/%d" % cid)
    assert b"Conferir regras de Limiar" in page.data


def test_atributo_zero_rola_dois_dados_e_pega_o_pior(mesa):
    cid = mesa.character("ana", slug="limiar", name="Zero")
    mesa.autosave("ana", cid, attr__poder="0")
    page = mesa.user("ana").get("/fichas/%d" % cid).data.decode()
    assert 'data-dice="0"' in page          # o servidor rola 2d20 e fica com o pior


def test_copia_do_sistema_mantem_as_regras(mesa):
    from app.blueprints.systems import clean_payload
    assert clean_payload(limiar_data())["rules"] == "limiar"
    assert clean_payload(dict(limiar_data(), rules="qualquer"))["rules"] == ""


def limiar_data():
    from app.presets import LIMIAR
    return json.loads(json.dumps(LIMIAR))
