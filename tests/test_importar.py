# -*- coding: utf-8 -*-
"""Importar uma campanha exportada."""
import io
import json
import zipfile

from app.models import Asset, Campaign, Character, Clock, Encounter, Note, TimelineEntry

from tests.conftest import png_file


def campanha_rica(mesa, app):
    """Uma campanha com um pouco de tudo, para exportar."""
    camp, code = mesa.campaign("mestre", name="Original", slug="dnd-5e")
    mesa.join("ana", code)
    kian = mesa.character("ana", camp, name="Kian")
    ghoul = mesa.character("mestre", camp, name="Ghoul", kind="criatura")
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/mapas" % camp, data={
        "title": "Cripta", "visibility": "mestre", "file": png_file()}, content_type="multipart/form-data")
    with app.app_context():
        map_id = Asset.query.filter_by(title="Cripta").one().id
    mestre.post("/campanhas/%d/anotacoes/nova" % camp, data={"title": "Segredo", "body": "o duque",
                                                            "visibility": "mestre"})
    mestre.post("/campanhas/%d/combate/novo" % camp, data={"name": "Emboscada"})
    base = "/campanhas/%d/combate/1" % camp
    mestre.post(base + "/adicionar", json={"party": True})
    state = mestre.post(base + "/adicionar", json={"character_id": ghoul}).get_json()
    uids = {c["name"]: c["uid"] for c in state["combatants"]}
    mestre.post(base + "/mapa/configurar", json={"map_id": map_id})
    mestre.post(base + "/mapa/mover", json={"uid": uids["Kian"], "x": 3, "y": 2})
    mestre.post("/campanhas/%d/relogios" % camp, json={"title": "Ritual", "segments": 8, "filled": 3})
    mestre.post("/campanhas/%d/tesouro" % camp, json={"op": "coins", "deltas": {"po": 50}})
    mestre.post("/campanhas/%d/calendario" % camp, data={"action": "setup", "preset": "gregoriano",
                                                        "year": "1492", "era": "DR"})
    mestre.post("/campanhas/%d/linha-do-tempo" % camp, data={
        "title": "Chegada", "world_day": "3", "world_month": "1", "world_year": "1492"})
    response = mestre.get("/campanhas/%d/exportar" % camp)
    data = response.data
    response.close()
    return camp, data


def importar(client, data, name="campanha.zip"):
    return client.post("/campanhas/importar", data={"file": (io.BytesIO(data), name)},
                       content_type="multipart/form-data")


def test_ida_e_volta(mesa, app):
    original, data = campanha_rica(mesa, app)
    novo = mesa.user("novomestre")
    response = importar(novo, data)
    assert response.status_code == 302, response.data[:500]

    with app.app_context():
        from app.extensions import db
        camp = Campaign.query.filter(Campaign.id != original, Campaign.name == "Original").one()
        assert camp.master.username == "novomestre"
        chars = {c.name: c for c in camp.characters.all()}
        assert set(chars) == {"Kian", "Ghoul"}
        assert chars["Kian"].owner.username == "novomestre" and chars["Kian"].imported_owner == "ana"
        assert chars["Ghoul"].imported_owner is None  # era do mestre
        assert Note.query.filter_by(campaign_id=camp.id, title="Segredo").one().visibility == "mestre"

        maps = Asset.query.filter_by(campaign_id=camp.id, kind="mapa").all()
        assert len(maps) == 1 and maps[0].visibility == "mestre"
        encounter = Encounter.query.filter_by(campaign_id=camp.id).one()
        linked = {c["name"]: c for c in encounter.combatants}
        assert linked["Kian"]["character_id"] == chars["Kian"].id  # religado à ficha nova
        assert encounter.board["map_id"] == maps[0].id
        assert encounter.board["tokens"][linked["Kian"]["uid"]]["x"] == 3

        clock = Clock.query.filter_by(campaign_id=camp.id).one()
        assert (clock.title, clock.segments, clock.filled) == ("Ritual", 8, 3)
        assert camp.treasure["coins"]["po"] == 50
        assert camp.calendar["era"] == "DR"
        entry = TimelineEntry.query.filter_by(campaign_id=camp.id).one()
        assert entry.world_day is not None
        assert camp.invite_code != db.session.get(Campaign, original).invite_code

    # A imagem do mapa foi copiada e abre para o novo mestre.
    image = novo.get(maps[0].url)
    assert image.status_code == 200
    image.close()

    # Entregar a ficha ao dono quando ele entrar.
    with app.app_context():
        code = camp.invite_code
        kian_id, camp_id = chars["Kian"].id, camp.id
    mesa.user("ana2").post("/campanhas/entrar", data={"invite_code": code})
    with app.app_context():
        from app.models import User
        ana2 = User.query.filter_by(username="ana2").one().id
    page = novo.get("/campanhas/%d/mesa" % camp_id).get_data(as_text=True)
    assert "Fichas importadas" in page and "era de ana" in page
    novo.post("/campanhas/%d/fichas/%d/entregar" % (camp_id, kian_id), data={"user_id": ana2})
    with app.app_context():
        from app.extensions import db
        kian = db.session.get(Character, kian_id)
        assert kian.owner_id == ana2 and kian.imported_owner is None


def test_entregar_so_para_quem_esta_na_mesa(mesa, app):
    original, data = campanha_rica(mesa, app)
    novo = mesa.user("novomestre")
    importar(novo, data)
    with app.app_context():
        camp = Campaign.query.filter(Campaign.id != original).one()
        kian = camp.characters.filter_by(name="Kian").one()
        camp_id, kian_id = camp.id, kian.id
        from app.models import User
        stranger = User.query.filter_by(username="ana").one().id  # não entrou nesta mesa
    novo.post("/campanhas/%d/fichas/%d/entregar" % (camp_id, kian_id), data={"user_id": stranger})
    with app.app_context():
        from app.extensions import db
        assert db.session.get(Character, kian_id).imported_owner == "ana"
    assert mesa.user("ana").post("/campanhas/%d/fichas/%d/entregar" % (camp_id, kian_id),
                                 data={"user_id": stranger}).status_code == 403


def _zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_arquivos_invalidos_sao_recusados_com_mensagem(mesa, app):
    client = mesa.user("mestre")
    cases = [
        (b"isso nao e zip", "não é um arquivo .zip"),
        (_zip({"outro.txt": "x"}), "campanha.json"),
        (_zip({"campanha.json": "{quebrado"}), "corrompido"),
        (_zip({"campanha.json": json.dumps({"formato": "outra-coisa"})}), "não é uma exportação"),
        (_zip({"campanha.json": json.dumps({"formato": "grimorio-campanha", "versao": 99})}), "versão mais nova"),
    ]
    for data, message in cases:
        response = importar(client, data)
        assert response.status_code == 400
        assert message in response.get_data(as_text=True), message
    with app.app_context():
        assert Campaign.query.count() == 0


def test_bomba_de_zip_e_recusada(mesa, app):
    bomb = _zip({"campanha.json": json.dumps({"formato": "grimorio-campanha", "versao": 2}),
                 "imagens/x.png": b"\0" * (30 * 1024 * 1024)})
    response = importar(mesa.user("mestre"), bomb)
    assert response.status_code == 400
    assert "grande demais" in response.get_data(as_text=True)


def test_dados_estranhos_nao_derrubam_nem_gravam_pela_metade(mesa, app):
    doc = {"formato": "grimorio-campanha", "versao": 2,
           "campanha": {"nome": "Estranha"}, "sistema": "texto em vez de objeto",
           "fichas": "não é lista", "mapas": [{"arquivo": ["lista"], "id": 1}],
           "combates": [{"nome": "C", "combatentes": ["x", {"name": "Solto"}],
                         "mapa_tatico": {"map_id": 1}}],
           "relogios": [{"title": "R", "segments": 999, "filled": -5}]}
    response = importar(mesa.user("mestre"), _zip({"campanha.json": json.dumps(doc)}))
    assert response.status_code == 302
    with app.app_context():
        camp = Campaign.query.filter_by(name="Estranha").one()
        clock = camp.clocks.one()
        assert (clock.segments, clock.filled) == (24, 0)
        enc = camp.encounters.one()
        assert [c["name"] for c in enc.combatants] == ["Solto"]
        assert enc.board["map_id"] is None


def test_falha_no_meio_nao_deixa_nada(mesa, app, monkeypatch):
    import os
    from app import importer
    original, data = campanha_rica(mesa, app)
    upload_dir = app.config["UPLOAD_DIR"]
    before = set(os.listdir(upload_dir))

    from app.extensions import db

    def explode(self, doc):
        self.image("imagens/" + [n for n in self.names if n.startswith("imagens/")][0].split("/", 1)[1],
                   "mapa", db.session.get(Campaign, original))
        raise RuntimeError("falhou no meio")
    monkeypatch.setattr(importer._Importer, "run", explode)
    response = importar(mesa.user("novomestre"), data)
    assert response.status_code == 400
    with app.app_context():
        assert Campaign.query.count() == 1
    assert set(os.listdir(upload_dir)) == before  # a imagem copiada foi apagada


def test_limite_de_tamanho_so_na_importacao(mesa, app):
    client = mesa.user("mestre")
    big = b"x" * (6 * 1024 * 1024)
    assert importar(client, big).status_code == 400  # passou do limite normal, chegou a validar
    camp, _ = mesa.campaign("mestre", name="Outra")
    response = client.post("/campanhas/%d/mapas" % camp, data={"file": (io.BytesIO(big), "a.png")},
                           content_type="multipart/form-data")
    assert response.status_code == 413
