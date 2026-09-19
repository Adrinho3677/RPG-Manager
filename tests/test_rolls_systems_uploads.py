# -*- coding: utf-8 -*-
"""Rolagens da mesa, sistemas (editor, exportar/importar) e envio de imagens."""
import io
import json
import os

from app.models import Asset, Character, GameSystem, RollLog
from tests.conftest import png_file


# ------------------------------------------------------------------ rolagens
def test_rolagem_da_ficha_entra_no_registro_da_mesa(mesa):
    camp, code = mesa.campaign("mestre")
    mesa.join("ana", code)
    cid = mesa.character("ana", camp)
    response = mesa.user("ana").post("/fichas/%d/rolar" % cid, json={"label": "Luta", "dice": 2, "bonus": 5})
    roll = response.get_json()["roll"]
    assert roll["who"] == "Kian" and roll["detail"].startswith("2d20 (maior)")

    feed = mesa.user("mestre").get("/campanhas/%d/rolagens" % camp).get_json()
    assert [r["label"] for r in feed["rolls"]] == ["Luta"]
    nada = mesa.user("mestre").get("/campanhas/%d/rolagens?desde=%d" % (camp, feed["last"])).get_json()
    assert nada["rolls"] == [] and nada["last"] == feed["last"]


def test_rolagem_secreta_so_para_o_mestre(mesa):
    camp, code = mesa.campaign("mestre")
    mesa.join("ana", code)
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/rolar" % camp, json={"formula": "1d20", "label": "Percepção do NPC", "secret": True})
    mestre.post("/campanhas/%d/rolar" % camp, json={"formula": "1d6", "label": "Aberta"})
    ana_feed = [r["label"] for r in mesa.user("ana").get("/campanhas/%d/rolagens" % camp).get_json()["rolls"]]
    assert ana_feed == ["Aberta"]
    # Jogador rolando "só o mestre vê": ele e o mestre veem; os outros jogadores não.
    mesa.join("bia", code)
    mesa.user("ana").post("/campanhas/%d/rolar" % camp, json={"formula": "1d4", "secret": True})
    with mesa.app.app_context():
        assert RollLog.query.filter_by(label="1d4").one().secret is True
    feed = lambda who: [r["label"] for r in mesa.user(who).get("/campanhas/%d/rolagens" % camp).get_json()["rolls"]]
    assert "1d4" in feed("ana") and "1d4" in feed("mestre")
    assert "1d4" not in feed("bia")


def test_parada_de_vampiro_nao_dobra(mesa):
    """Regressão: a perícia mandava o total como dados E como bônus."""
    cid = mesa.character("ana", slug="vampiro-a-mascara", name="Cainita")
    page = mesa.user("ana").get("/fichas/%d" % cid).data.decode()
    import re
    button = re.search(r'data-label="Briga"\s+data-dice="(\d+)" data-bonus="(\d+)"', page)
    assert button and button.group(2) == "0"
    roll = mesa.user("ana").post("/fichas/%d/rolar" % cid,
                                 json={"dice": int(button.group(1)), "bonus": 0}).get_json()["roll"]
    assert roll["detail"].startswith("%sd10" % button.group(1))


def test_so_quem_edita_rola_pela_ficha(mesa):
    camp, code = mesa.campaign("mestre")
    mesa.join("ana", code)
    mesa.join("bruno", code)
    cid = mesa.character("ana", camp)
    assert mesa.user("bruno").post("/fichas/%d/rolar" % cid, json={"dice": 1}).status_code == 403


def test_rolagem_invalida_explica(mesa):
    cid = mesa.character("ana")
    response = mesa.user("ana").post("/fichas/%d/rolar" % cid, json={"formula": "abc"})
    assert response.status_code == 400 and "2d6" in response.get_json()["message"]


def test_excluir_ficha_preserva_as_rolagens(mesa):
    camp, _ = mesa.campaign("mestre")
    cid = mesa.character("mestre", camp)
    mesa.user("mestre").post("/fichas/%d/rolar" % cid, json={"dice": 1})
    mesa.user("mestre").post("/fichas/%d/excluir" % cid)
    with mesa.app.app_context():
        roll = RollLog.query.one()
        assert roll.character_id is None and roll.as_dict()["who"] == "mestre"


# ------------------------------------------------------------------ sistemas
def test_duplicar_e_salvar_preserva_carga_rotulos_e_descanso(mesa):
    client = mesa.user("ana")
    client.post("/sistemas/%d/duplicar" % mesa.system_id("ordem-paranormal"))
    with mesa.app.app_context():
        system = GameSystem.query.filter_by(is_preset=False).one()
        sid, data = system.id, system.data
    client.post("/sistemas/%d/editar" % sid, data={"name": "Minha Ordem", "payload": json.dumps(data)})
    saved = mesa.get(GameSystem, sid).data
    assert saved["inventory"]["mode"] == "slots"
    assert saved["labels"]["spells"] == "Rituais"
    assert saved["bars"][2]["rest_long"]["mode"] == "none"


def test_payload_vazio_ou_quebrado_nao_apaga_o_sistema(mesa):
    client = mesa.user("ana")
    client.post("/sistemas/%d/duplicar" % mesa.system_id("ordem-paranormal"))
    sid = 7
    for bad in ("", "nao-e-json", "[]", "{}"):
        client.post("/sistemas/%d/editar" % sid, data={"name": "X", "payload": bad})
        assert len(mesa.get(GameSystem, sid).attributes) == 5


def test_formula_invalida_gera_aviso(mesa):
    client = mesa.user("ana")
    client.post("/sistemas/%d/duplicar" % mesa.system_id("generico"))
    data = mesa.get(GameSystem, 7).data
    data["bars"][0]["max_formula"] = "10 + FORCA_INEXISTENTE"
    page = client.post("/sistemas/7/editar", data={"name": "G", "payload": json.dumps(data)},
                       follow_redirects=True)
    assert "FORCA_INEXISTENTE".encode() in page.data


def test_exportar_e_importar(mesa):
    client = mesa.user("ana")
    exported = client.get("/sistemas/%d/exportar" % mesa.system_id("tormenta-20"))
    assert exported.status_code == 200
    assert "attachment" in exported.headers["Content-Disposition"]

    other = mesa.user("bruno")
    page = other.post("/sistemas/importar", data={"file": (io.BytesIO(exported.data), "t20.grimorio.json")},
                      content_type="multipart/form-data", follow_redirects=True)
    assert "Tormenta 20 (importado)".encode() in page.data
    with mesa.app.app_context():
        imported = GameSystem.query.filter(GameSystem.name.like("%importado%")).one()
        assert imported.owner.username == "bruno"
        assert imported.data["labels"]["spells"] == "Magias"
        assert len(imported.skills) == 29


def test_importar_lixo_nao_quebra(mesa):
    client = mesa.user("ana")
    for content in ("isso não é json", '{"formato": "outro"}',
                    '{"formato": "grimorio-sistema", "dados": {"attributes": [1, "x", null], "bars": "?"}}',
                    '{"formato": "grimorio-sistema", "dados": []}'):
        response = client.post("/sistemas/importar", data={"content": content})
        assert response.status_code == 200
    with mesa.app.app_context():
        assert GameSystem.query.filter_by(is_preset=False).count() == 0


def test_sistema_de_outro_usuario_nao_exporta(mesa):
    mesa.user("ana").post("/sistemas/%d/duplicar" % mesa.system_id("generico"))
    assert mesa.user("bruno").get("/sistemas/7/exportar").status_code == 403


# -------------------------------------------------------------------- imagens
def test_retrato_enviado_vira_arquivo_servido(mesa):
    cid = mesa.character("ana")
    client = mesa.user("ana")
    client.post("/fichas/%d/identidade" % cid, data={"name": "Kian", "avatar_file": png_file()},
                content_type="multipart/form-data")
    url = mesa.sheet(cid).avatar_url
    assert url.startswith("/arquivos/")
    served = client.get(url)
    assert served.status_code == 200 and served.mimetype == "image/png"
    assert served.headers["X-Content-Type-Options"] == "nosniff"
    served.close()  # no Windows, arquivo aberto não pode ser apagado

    client.post("/fichas/%d/identidade" % cid, data={"name": "Kian", "avatar_file": png_file("outro.png")},
                content_type="multipart/form-data")
    with mesa.app.app_context():
        assert Asset.query.count() == 1                     # o antigo foi apagado
        assert len(os.listdir(mesa.app.config["UPLOAD_DIR"])) == 1


def test_arquivo_disfarcado_de_imagem_e_recusado(mesa):
    cid = mesa.character("ana")
    client = mesa.user("ana")
    for payload, name in ((b"<svg onload=alert(1)>", "x.png"), (b"<script>alert(1)</script>", "x.jpg"),
                          (b"MZ\x90\x00", "virus.gif")):
        page = client.post("/fichas/%d/identidade" % cid,
                           data={"name": "Kian", "avatar_file": (io.BytesIO(payload), name)},
                           content_type="multipart/form-data", follow_redirects=True)
        assert "PNG, JPG, GIF ou WEBP".encode() in page.data
    with mesa.app.app_context():
        assert Asset.query.count() == 0


def test_mapa_escondido_nao_e_entregue_ao_jogador(mesa):
    camp, code = mesa.campaign("mestre")
    mesa.join("ana", code)
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/mapas" % camp, data={"file": png_file("mapa.png"), "title": "Covil",
                                                     "visibility": "mestre"},
                content_type="multipart/form-data")
    with mesa.app.app_context():
        asset = Asset.query.one()
        url, asset_id = asset.url, asset.id

    ana = mesa.user("ana")
    assert b"Covil" not in ana.get("/campanhas/%d/mapas" % camp).data
    assert ana.get(url).status_code == 404
    assert mesa.user("estranho").get(url).status_code == 404

    mestre.post("/campanhas/%d/mapas/%d/revelar" % (camp, asset_id))
    assert b"Covil" in ana.get("/campanhas/%d/mapas" % camp).data
    assert ana.get(url).status_code == 200
    assert mesa.user("estranho").get(url).status_code == 404     # fora da mesa, nunca


def test_jogador_nao_esconde_imagem_e_nao_apaga_a_dos_outros(mesa):
    camp, code = mesa.campaign("mestre")
    mesa.join("ana", code)
    mesa.join("bruno", code)
    mesa.user("ana").post("/campanhas/%d/mapas" % camp,
                          data={"file": png_file(), "title": "Rascunho", "visibility": "mestre"},
                          content_type="multipart/form-data")
    with mesa.app.app_context():
        asset = Asset.query.one()
        assert asset.visibility == "mesa"
        asset_id = asset.id
    assert mesa.user("bruno").post("/campanhas/%d/mapas/%d/excluir" % (camp, asset_id)).status_code == 403
    assert mesa.user("ana").post("/campanhas/%d/mapas/%d/revelar" % (camp, asset_id)).status_code == 403


def test_excluir_campanha_apaga_os_arquivos(mesa):
    camp, _ = mesa.campaign("mestre")
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/mapas" % camp, data={"file": png_file(), "title": "M"},
                content_type="multipart/form-data")
    assert len(os.listdir(mesa.app.config["UPLOAD_DIR"])) == 1
    mestre.post("/campanhas/%d/excluir" % camp)
    assert os.listdir(mesa.app.config["UPLOAD_DIR"]) == []


def test_todas_as_paginas_abrem(mesa):
    """Varredura: nenhuma página principal quebra ao renderizar, para mestre e jogador."""
    camp, code = mesa.campaign("mestre")
    mesa.join("ana", code)
    cid = mesa.character("ana", camp)
    mesa.character("mestre", camp, name="Ghoul", kind="criatura")
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/sessoes/nova" % camp, data={"title": "S"})
    mestre.post("/campanhas/%d/combate/novo" % camp, data={"name": "C"})
    mestre.post("/campanhas/%d/anotacoes/nova" % camp, data={"title": "N", "body": "b"})
    pages = ["/painel", "/fichas/", "/sistemas/", "/sistemas/1", "/sistemas/novo", "/sistemas/importar",
             "/conta", "/campanhas/%d" % camp, "/campanhas/%d/sessoes" % camp,
             "/campanhas/%d/sessoes/1" % camp, "/campanhas/%d/anotacoes" % camp,
             "/campanhas/%d/anotacoes/1/editar" % camp, "/campanhas/%d/anotacoes/nova" % camp,
             "/campanhas/%d/elenco" % camp, "/campanhas/%d/combate" % camp, "/campanhas/%d/mapas" % camp,
             "/campanhas/%d/linha-do-tempo" % camp, "/campanhas/%d/mesa" % camp,
             "/fichas/%d" % cid, "/fichas/%d/imprimir" % cid, "/fichas/nova?campanha=%d" % camp]
    for who in ("mestre", "ana"):
        for path in pages:
            status = mesa.user(who).get(path).status_code
            assert status == 200, "%s em %s deu %s" % (who, path, status)
    mestre.post("/sistemas/1/duplicar")
    assert mestre.get("/sistemas/7/editar").status_code == 200
