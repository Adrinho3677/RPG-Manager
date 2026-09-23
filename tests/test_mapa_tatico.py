# -*- coding: utf-8 -*-
"""Mapa tático: quem move o quê, névoa, fichas escondidas e a imagem do mapa."""
import json
import threading

from app import board as board_helper
from app.models import Asset, Encounter

from tests.conftest import png_file


def mesa_de_combate(mesa):
    camp, code = mesa.campaign("mestre")
    mesa.join("ana", code)
    mesa.join("bia", code)
    kian = mesa.character("ana", camp, name="Kian")
    mesa.character("bia", camp, name="Lia")
    ghoul = mesa.character("mestre", camp, name="Ghoul", kind="criatura")
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/combate/novo" % camp, data={"name": "Emboscada"})
    base = "/campanhas/%d/combate/1" % camp
    mestre.post(base + "/adicionar", json={"party": True})
    state = mestre.post(base + "/adicionar", json={"character_id": ghoul, "quantity": 2}).get_json()
    uids = {c["name"]: c["uid"] for c in state["combatants"]}
    return camp, base, uids, kian


def test_mestre_posiciona_e_todos_veem(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")

    inicio = mestre.get(base + "/mapa").get_json()
    assert inicio["tokens"] == [] and len(inicio["bench"]) == 4  # tudo fora do mapa

    state = mestre.post(base + "/mapa/mover", json={"uid": uids["Ghoul 1"], "x": 5, "y": 3}).get_json()
    assert [(t["name"], t["x"], t["y"]) for t in state["tokens"]] == [("Ghoul 1", 5, 3)]

    visto = ana.get(base + "/mapa").get_json()
    assert [t["name"] for t in visto["tokens"]] == ["Ghoul 1"]
    assert "hp" not in visto["tokens"][0]            # PV de inimigo não vai para jogador
    assert visto["tokens"][0]["health"] == "ileso"
    assert [t["name"] for t in visto["bench"]] == ["Kian"]  # só a ficha dela fica "na mão"
    assert "maps" not in visto


def test_jogador_move_so_a_propria_ficha(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    ana = mesa.user("ana")

    ok = ana.post(base + "/mapa/mover", json={"uid": uids["Kian"], "x": 1, "y": 1})
    assert ok.status_code == 200
    assert ok.get_json()["tokens"][0]["can_move"] is True

    assert ana.post(base + "/mapa/mover", json={"uid": uids["Lia"], "x": 2, "y": 2}).status_code == 403
    assert ana.post(base + "/mapa/mover", json={"uid": uids["Ghoul 1"], "x": 2, "y": 2}).status_code == 403
    assert ana.post(base + "/mapa/mover", json={"uid": "naoexiste", "x": 2, "y": 2}).status_code == 404
    assert ana.post(base + "/mapa/mover", json={"uid": uids["Kian"], "x": 99, "y": 0}).status_code == 400


def test_mestre_trava_o_mapa(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    mestre.post(base + "/mapa/mover", json={"uid": uids["Kian"], "x": 0, "y": 0})
    mestre.post(base + "/mapa/configurar", json={"players_move": False})

    blocked = ana.post(base + "/mapa/mover", json={"uid": uids["Kian"], "x": 1, "y": 0})
    assert blocked.status_code == 403
    assert ana.get(base + "/mapa").get_json()["tokens"][0]["can_move"] is False


def test_so_o_mestre_configura_esconde_e_pinta_nevoa(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    ana = mesa.user("ana")
    assert ana.post(base + "/mapa/configurar", json={"cols": 5}).status_code == 403
    assert ana.post(base + "/mapa/esconder", json={"uid": uids["Kian"], "hidden": True}).status_code == 403
    assert ana.post(base + "/mapa/nevoa", json={"all": True, "reveal": True}).status_code == 403


def test_ficha_escondida_nao_chega_ao_jogador(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    mestre.post(base + "/mapa/mover", json={"uid": uids["Ghoul 2"], "x": 4, "y": 4})
    state = mestre.post(base + "/mapa/esconder", json={"uid": uids["Ghoul 2"], "hidden": True}).get_json()
    assert state["tokens"][0]["hidden"] is True  # o mestre continua vendo

    body = ana.get(base + "/mapa").get_data(as_text=True)
    assert "Ghoul 2" not in body and uids["Ghoul 2"] not in body

    # Nem no rastreador de iniciativa, nem na página.
    tracker = ana.get(base + "/estado").get_data(as_text=True)
    assert "Ghoul 2" not in tracker and uids["Ghoul 2"] not in tracker
    page = ana.get("/campanhas/%d/combate" % camp).get_data(as_text=True)
    assert "Ghoul 2" not in page
    assert "Ghoul 2" in mesa.user("mestre").get(base + "/estado").get_data(as_text=True)


def test_turno_continua_certo_com_ficha_escondida(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    ordem = [c["name"] for c in mestre.get(base + "/estado").get_json()["combatants"]]
    escondido = ordem[1]
    mestre.post(base + "/mapa/mover", json={"uid": uids[escondido], "x": 0, "y": 0})
    mestre.post(base + "/mapa/esconder", json={"uid": uids[escondido], "hidden": True})

    def vez_para(turn):
        state = mestre.get(base + "/estado").get_json()
        state["turn_index"] = turn
        mestre.post(base + "/salvar", json=state)
        visto = ana.get(base + "/estado").get_json()
        i = visto["turn_index"]
        return visto["combatants"][i]["name"] if i >= 0 else None

    assert vez_para(0) == ordem[0]
    assert vez_para(1) is None          # vez do escondido: ninguém destacado
    assert vez_para(2) == ordem[2]      # e o seguinte continua certo


def test_nevoa_esconde_inimigos_mas_nao_o_grupo(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    mestre.post(base + "/mapa/mover", json={"uid": uids["Ghoul 1"], "x": 8, "y": 8})
    mestre.post(base + "/mapa/mover", json={"uid": uids["Lia"], "x": 9, "y": 9})
    mestre.post(base + "/mapa/configurar", json={"fog": True})

    names = [t["name"] for t in ana.get(base + "/mapa").get_json()["tokens"]]
    assert names == ["Lia"]  # ligar a névoa cobre tudo; a aliada aparece mesmo assim

    # A sala do ghoul: forma cortada abre um buraco na névoa.
    state = forma(mestre, base, "rect", [[8, 8], [9, 9]]).get_json()
    sala = state["fog_layer"]["shapes"][0]
    assert state["fog_layer"]["fill"] is True and sala["cut"] is True
    assert sorted(t["name"] for t in ana.get(base + "/mapa").get_json()["tokens"]) == ["Ghoul 1", "Lia"]

    # Fim da cena: a mesma forma volta a cobrir, sem redesenhar nada.
    mestre.post(base + "/mapa/nevoa", json={"op": "uncut", "id": sala["id"]})
    assert [t["name"] for t in ana.get(base + "/mapa").get_json()["tokens"]] == ["Lia"]


def test_grade_menor_traz_fichas_para_dentro(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre = mesa.user("mestre")
    mestre.post(base + "/mapa/mover", json={"uid": uids["Kian"], "x": 19, "y": 13})
    mestre.post(base + "/mapa/configurar", json={"fog": True})
    forma(mestre, base, "rect", [[2, 2], [3, 3]])
    state = mestre.post(base + "/mapa/configurar", json={"cols": 10, "rows": 5}).get_json()
    assert (state["tokens"][0]["x"], state["tokens"][0]["y"]) == (9, 4)
    assert len(state["fog_layer"]["shapes"]) == 1   # a forma sobrevive ao redimensionar

    bad = mestre.post(base + "/mapa/configurar", json={"cell_size": "0"})
    assert bad.status_code == 400
    huge = mestre.post(base + "/mapa/configurar", json={"cols": 5000})
    assert huge.status_code == 400 and "quebrado" in huge.get_json()["message"]

    # Grade quebrada: 18,5 × 2,87 (o último quadrado de cada borda fica parcial).
    state = mestre.post(base + "/mapa/configurar", json={"cols": "18,5", "rows": 2.87}).get_json()
    assert (state["cols"], state["rows"]) == (18.5, 2.87)
    assert board_helper.cells_across(18.5) == 19 and board_helper.cells_across(2.87) == 3
    assert mestre.post(base + "/mapa/mover", json={"uid": uids["Kian"], "x": 18, "y": 2}).status_code == 200
    assert mestre.post(base + "/mapa/mover", json={"uid": uids["Kian"], "x": 19, "y": 0}).status_code == 400


def test_salvar_rastreador_nao_apaga_posicoes(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre = mesa.user("mestre")
    mestre.post(base + "/mapa/mover", json={"uid": uids["Kian"], "x": 3, "y": 3})
    state = mestre.get(base + "/estado").get_json()
    state["round_number"] = 2
    mestre.post(base + "/salvar", json=state)
    tokens = mestre.get(base + "/mapa").get_json()["tokens"]
    assert [(t["name"], t["x"]) for t in tokens] == [("Kian", 3)]

    # Tirou do rastreador: some do mapa também.
    state = mestre.get(base + "/estado").get_json()
    state["combatants"] = [c for c in state["combatants"] if c["name"] != "Kian"]
    mestre.post(base + "/salvar", json=state)
    assert mestre.get(base + "/mapa").get_json()["tokens"] == []


def test_mapa_escondido_na_galeria_fica_visivel_quando_usado(mesa, app):
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    mestre.post("/campanhas/%d/mapas" % camp, data={
        "title": "Cripta", "visibility": "mestre", "file": png_file("cripta.png")},
        content_type="multipart/form-data")
    with app.app_context():
        asset = Asset.query.filter_by(title="Cripta").one()
        asset_id, url = asset.id, asset.url

    assert ana.get(url).status_code == 404
    state = mestre.post(base + "/mapa/configurar", json={"map_id": asset_id}).get_json()
    assert state["map_url"] == url
    response = ana.get(url)
    assert response.status_code == 200
    response.close()

    # Mapa de outra campanha não entra.
    outra, _ = mesa.campaign("mestre", name="Outra")
    mestre.post("/campanhas/%d/combate/novo" % outra, data={"name": "Outro combate"})
    with app.app_context():
        other_id = Encounter.query.filter_by(campaign_id=outra).one().id
    recusado = mestre.post("/campanhas/%d/combate/%d/mapa/configurar" % (outra, other_id),
                           json={"map_id": asset_id})
    assert recusado.status_code == 400
    assert "não é desta campanha" in recusado.get_json()["message"]


def test_quem_nao_e_da_mesa_nao_ve_o_mapa(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    assert mesa.user("intruso").get(base + "/mapa").status_code == 403


def test_movimentos_simultaneos_nao_se_perdem(mesa, app):
    """Duas pessoas movendo ao mesmo tempo: as duas posições ficam."""
    camp, base, uids, _ = mesa_de_combate(mesa)
    names = ["Kian", "Lia", "Ghoul 1", "Ghoul 2"]
    clients = [app.test_client() for _ in names]
    for client in clients:
        client.post("/entrar", data={"identifier": "mestre", "password": "segredo123"})
    errors = []

    def mover(client, name, x):
        response = client.post(base + "/mapa/mover", json={"uid": uids[name], "x": x, "y": x})
        if response.status_code != 200:
            errors.append(response.status_code)

    threads = [threading.Thread(target=mover, args=(c, n, i)) for i, (c, n) in enumerate(zip(clients, names))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    tokens = mesa.user("mestre").get(base + "/mapa").get_json()["tokens"]
    assert sorted(t["name"] for t in tokens) == sorted(names)


def test_normalize_ignora_lixo():
    board = board_helper.normalize({"cols": "abc", "rows": -3, "revealed": ["1,1", "x", "99,99"],
                                    "tokens": {"a": {"x": 500, "y": -1}, "b": "lixo"},
                                    "cell_size": "nan"})
    assert (board["cols"], board["rows"]) == (20, 14)  # lixo volta ao padrão
    assert board["tokens"] == {"a": {"x": 19, "y": 0, "hidden": False, "size": 1}}
    # "1,1" da névoa antiga virou forma cortada; "x" e "99,99" saem
    assert board["revealed"] == []
    shapes = board["fog_layer"]["shapes"]
    assert [(s["kind"], s["cut"], s["points"]) for s in shapes] == [("rect", True, [[1, 1], [2, 2]])]


def test_exportacao_leva_o_mapa(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre = mesa.user("mestre")
    mestre.post(base + "/mapa/mover", json={"uid": uids["Kian"], "x": 2, "y": 1})
    import io
    import zipfile
    response = mestre.get("/campanhas/%d/exportar" % camp)
    data = json.loads(zipfile.ZipFile(io.BytesIO(response.data)).read("campanha.json"))
    response.close()
    assert data["combates"][0]["mapa_tatico"]["tokens"][uids["Kian"]]["x"] == 2


def test_pagina_de_combate_mostra_o_mapa(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    html = mesa.user("ana").get("/campanhas/%d/combate" % camp).get_data(as_text=True)
    assert "data-board-payload" in html and "board.js" in html
    assert "data-config-url" not in html  # jogador não recebe as ferramentas do mestre


# ------------------------------------------------ áreas, marcadores e névoa real
def test_areas_de_efeito_quem_pode_por_e_tirar(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana, bia = mesa.user("mestre"), mesa.user("ana"), mesa.user("bia")
    state = ana.post(base + "/mapa/area", json={"op": "add", "shape": "cone", "ox": 2.5, "oy": 2.5,
                                                "angle": 90, "size": 4}).get_json()
    area = state["areas"][0]
    assert (area["shape"], area["who"], area["size"]) == ("cone", "ana", 4)
    assert bia.post(base + "/mapa/area", json={"op": "remove", "id": area["id"]}).status_code == 400
    assert bia.post(base + "/mapa/area", json={"op": "clear"}).status_code == 403
    assert ana.post(base + "/mapa/area", json={"op": "add", "shape": "estrela", "size": 2}).status_code == 400
    assert ana.post(base + "/mapa/area", json={"op": "add", "shape": "circle", "size": 0}).status_code == 400
    ana.post(base + "/mapa/area", json={"op": "remove", "id": area["id"]})
    assert mestre.get(base + "/mapa").get_json()["areas"] == []

    mestre.post(base + "/mapa/area", json={"op": "add", "shape": "circle", "ox": 1, "oy": 1, "size": 2})
    ana.post(base + "/mapa/area", json={"op": "add", "shape": "line", "ox": 1, "oy": 1, "size": 3})
    assert mestre.post(base + "/mapa/area", json={"op": "clear"}).get_json()["areas"] == []


def test_marcadores_comecam_escondidos_e_o_mestre_revela(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    state = mestre.post(base + "/mapa/marcador", json={"op": "add", "type": "armadilha", "x": 3, "y": 4,
                                                       "label": "fosso"}).get_json()
    marker = state["markers"][0]
    assert marker["hidden"] is True and marker["icon"] == "⚠️"

    body = ana.get(base + "/mapa").get_data(as_text=True)
    assert "fosso" not in body and marker["id"] not in body

    mestre.post(base + "/mapa/marcador", json={"op": "update", "id": marker["id"], "hidden": False})
    visto = ana.get(base + "/mapa").get_json()["markers"]
    assert [(m["label"], m["x"], m["y"]) for m in visto] == [("fosso", 3, 4)]
    assert "hidden" not in visto[0]

    # Debaixo da névoa, some de novo para o jogador.
    mestre.post(base + "/mapa/configurar", json={"fog": True})
    assert ana.get(base + "/mapa").get_json()["markers"] == []
    forma(mestre, base, "rect", [[3, 4], [4, 5]])
    assert len(ana.get(base + "/mapa").get_json()["markers"]) == 1

    assert ana.post(base + "/mapa/marcador", json={"op": "add", "type": "porta", "x": 0, "y": 0}).status_code == 403
    assert mestre.post(base + "/mapa/marcador", json={"op": "add", "type": "bomba", "x": 0, "y": 0}).status_code == 400
    mestre.post(base + "/mapa/marcador", json={"op": "update", "id": marker["id"], "x": 5, "y": 5})
    mestre.post(base + "/mapa/marcador", json={"op": "remove", "id": marker["id"]})
    assert mestre.get(base + "/mapa").get_json()["markers"] == []


def _png(width, height, color):
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "PNG")
    buffer.seek(0)
    return buffer


def test_nevoa_real_recorta_a_imagem_no_servidor(mesa, app):
    import io
    from PIL import Image
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    mestre.post("/campanhas/%d/mapas" % camp, data={
        "title": "Cripta", "visibility": "mestre", "file": (_png(200, 100, (250, 250, 250)), "c.png")},
        content_type="multipart/form-data")
    with app.app_context():
        asset = Asset.query.filter_by(title="Cripta").one()
        asset_id, original = asset.id, asset.url
    mestre.post(base + "/mapa/configurar", json={"map_id": asset_id, "cols": 2, "rows": 1, "fog": True})
    forma(mestre, base, "rect", [[0, 0], [1, 1]])

    visto = ana.get(base + "/mapa").get_json()
    assert visto["map_url"] != original and "/mapa/imagem" in visto["map_url"]
    assert mestre.get(base + "/mapa").get_json()["map_url"] == original

    # O original não abre para o jogador enquanto houver névoa.
    assert ana.get(original).status_code == 404

    response = ana.get(visto["map_url"])
    assert response.status_code == 200 and response.mimetype == "image/jpeg"
    image = Image.open(io.BytesIO(response.data)).convert("RGB")
    response.close()
    left, right = image.getpixel((50, 50)), image.getpixel((150, 50))
    assert min(left) > 200          # revelado: a imagem de verdade
    assert max(right) < 30          # não revelado: preto

    # Revelar mais muda a URL (o navegador não fica com a versão velha).
    mestre.post(base + "/mapa/nevoa", json={"op": "clear"})
    assert ana.get(base + "/mapa").get_json()["map_url"] != visto["map_url"]

    # Sem névoa, volta a ser o original.
    mestre.post(base + "/mapa/configurar", json={"fog": False})
    assert ana.get(base + "/mapa").get_json()["map_url"] == original
    ok = ana.get(original)
    assert ok.status_code == 200
    ok.close()
    assert mesa.user("intruso").get(visto["map_url"]).status_code == 403


# ------------------------------------------ névoa por formas (Owlbear Rodeo)
def forma(client, base, kind, points, cut=True, size=1.0):
    """Desenha uma forma de névoa. Cortada (cut) = abre buraco na névoa."""
    return client.post(base + "/mapa/nevoa",
                       json={"op": "add", "kind": kind, "points": points, "size": size, "cut": cut})


def test_sala_redonda_revela_so_o_circulo(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    mestre.post(base + "/mapa/configurar", json={"fog": True})
    mestre.post(base + "/mapa/mover", json={"uid": uids["Ghoul 1"], "x": 5, "y": 5})
    mestre.post(base + "/mapa/mover", json={"uid": uids["Ghoul 2"], "x": 12, "y": 5})
    assert ana.get(base + "/mapa").get_json()["tokens"] == []

    # Sala redonda em volta do Ghoul 1 (centro do quadrado 5,5) — o quadrado
    # nunca tamparia isso direito.
    state = forma(mestre, base, "circle", [[5.5, 5.5]], size=1.2).get_json()
    assert state["fog_layer"]["shapes"][0]["kind"] == "circle"
    assert [t["name"] for t in ana.get(base + "/mapa").get_json()["tokens"]] == ["Ghoul 1"]

    # Corredor à mão livre até o outro: o pincel também vira forma.
    forma(mestre, base, "brush", [[5.5, 5.5], [8, 5.5], [12.5, 5.5]], size=0.6)
    assert sorted(t["name"] for t in ana.get(base + "/mapa").get_json()["tokens"]) == ["Ghoul 1", "Ghoul 2"]

    # "Limpar" apaga tudo e o mapa fica à mostra.
    state = mestre.post(base + "/mapa/nevoa", json={"op": "clear"}).get_json()
    assert state["fog_layer"] == {"fill": False, "shapes": []}
    assert len(ana.get(base + "/mapa").get_json()["tokens"]) == 2


def test_forma_solta_cobre_e_cortada_abre_buraco(mesa):
    """Sem 'cobrir tudo': só a mancha desenhada esconde — e um corte nela revela."""
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    mestre.post(base + "/mapa/mover", json={"uid": uids["Ghoul 1"], "x": 5, "y": 5})
    mestre.post(base + "/mapa/mover", json={"uid": uids["Ghoul 2"], "x": 15, "y": 5})
    mestre.post(base + "/mapa/configurar", json={"fog": True})
    mestre.post(base + "/mapa/nevoa", json={"op": "fill", "value": False})
    assert sorted(t["name"] for t in ana.get(base + "/mapa").get_json()["tokens"]) == [
        "Ghoul 1", "Ghoul 2"]

    # Um polígono cobrindo o canto onde está o Ghoul 1.
    poly = forma(mestre, base, "poly", [[4, 4], [8, 4], [8, 8], [4, 8]], cut=False).get_json()
    assert "Ghoul 1" not in [t["name"] for t in ana.get(base + "/mapa").get_json()["tokens"]]

    # Buraco redondo bem em cima dele: forma cortada vence a névoa toda.
    forma(mestre, base, "circle", [[5.5, 5.5]], size=0.8)
    assert "Ghoul 1" in [t["name"] for t in ana.get(base + "/mapa").get_json()["tokens"]]

    # Apagar o polígono não deixa resto.
    mestre.post(base + "/mapa/nevoa", json={"op": "remove", "id": poly["fog_layer"]["shapes"][0]["id"]})
    state = mestre.get(base + "/mapa").get_json()
    assert [s["kind"] for s in state["fog_layer"]["shapes"]] == ["circle"]


def test_revelar_e_cobrir_a_mesma_sala(mesa):
    """O jeito de jogar: salas desenhadas antes, reveladas com um clique."""
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    mestre.post(base + "/mapa/mover", json={"uid": uids["Ghoul 1"], "x": 3, "y": 3})
    mestre.post(base + "/mapa/configurar", json={"fog": True})
    sala = forma(mestre, base, "rect", [[2, 2], [6, 6]], cut=False).get_json()["fog_layer"]["shapes"][0]
    assert ana.get(base + "/mapa").get_json()["tokens"] == []

    for _ in range(2):   # revela, cobre, revela de novo: sempre a mesma forma
        state = mestre.post(base + "/mapa/nevoa", json={"op": "toggle", "id": sala["id"]}).get_json()
        assert state["fog_layer"]["shapes"][0]["cut"] is True
        assert [t["name"] for t in ana.get(base + "/mapa").get_json()["tokens"]] == ["Ghoul 1"]
        mestre.post(base + "/mapa/nevoa", json={"op": "uncut", "id": sala["id"]})
        assert ana.get(base + "/mapa").get_json()["tokens"] == []

    sumida = mestre.post(base + "/mapa/nevoa", json={"op": "cut", "id": "nao-existe"})
    assert sumida.status_code == 400
    assert "não está mais no mapa" in sumida.get_json()["message"]


def test_nevoa_antiga_por_quadrados_vira_forma(mesa):
    """Mapa salvo antes das formas: os quadrados revelados continuam revelados."""
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    mestre.post(base + "/mapa/mover", json={"uid": uids["Ghoul 1"], "x": 3, "y": 3})
    mestre.post(base + "/mapa/configurar", json={"fog": True})
    with mesa.app.app_context():
        from app.extensions import db
        from app.models import Encounter
        encounter = Encounter.query.one()
        board = dict(encounter.board)
        board["revealed"] = ["3,3"]                     # como o banco antigo guardava
        board["fog_layer"] = {"base": "cover", "strokes": []}
        encounter.board = board
        db.session.commit()

    assert [t["name"] for t in ana.get(base + "/mapa").get_json()["tokens"]] == ["Ghoul 1"]
    state = mestre.get(base + "/mapa").get_json()
    assert state["fog_layer"]["fill"] is True
    assert [(s["kind"], s["cut"]) for s in state["fog_layer"]["shapes"]] == [("rect", True)]


def test_limite_de_formas(mesa):
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre = mesa.user("mestre")
    mestre.post(base + "/mapa/configurar", json={"fog": True})
    linha = [[x / 10.0, 1] for x in range(400)]
    for _ in range(40):  # 40 × 400 pontos passa do teto de 12.000
        response = forma(mestre, base, "brush", linha)
        if response.status_code == 400:
            assert "complexa demais" in response.get_json()["message"]
            break
    else:
        raise AssertionError("o limite de formas não foi aplicado")

    torta = forma(mestre, base, "poly", [[1, 1]])
    assert torta.status_code == 400 and "inválida" in torta.get_json()["message"]


def test_imagem_recortada_segue_as_formas(mesa, app):
    import io
    from PIL import Image
    camp, base, uids, _ = mesa_de_combate(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    mestre.post("/campanhas/%d/mapas" % camp, data={
        "title": "Sala redonda", "visibility": "mestre", "file": (_png(200, 200, (250, 250, 250)), "s.png")},
        content_type="multipart/form-data")
    with app.app_context():
        asset_id = Asset.query.filter_by(title="Sala redonda").one().id
    mestre.post(base + "/mapa/configurar", json={"map_id": asset_id, "cols": 10, "rows": 10, "fog": True})
    forma(mestre, base, "circle", [[5, 5]], size=2)  # sala redonda no meio

    url = ana.get(base + "/mapa").get_json()["map_url"]
    response = ana.get(url)
    image = Image.open(io.BytesIO(response.data)).convert("RGB")
    response.close()
    assert min(image.getpixel((100, 100))) > 200   # meio: revelado
    assert max(image.getpixel((100, 20))) < 30     # acima do círculo: coberto
    assert max(image.getpixel((10, 10))) < 30      # canto: coberto
