# -*- coding: utf-8 -*-
"""Histórico da ficha, convite por link, limite de login e exportação."""
import io
import json
import shutil
import zipfile
from datetime import datetime, timedelta

from app.models import Campaign, CampaignMember, CharacterRevision, LoginAttempt
from tests.conftest import make_config, png_file


def mesa_com_ficha(mesa):
    camp, code = mesa.campaign("mestre")
    mesa.join("ana", code)
    cid = mesa.character("ana", camp)
    return camp, code, cid


def revisions(mesa, cid):
    with mesa.app.app_context():
        return [(r.reason, r.author.username if r.author else None, r.changed_list, r.data)
                for r in CharacterRevision.query.filter_by(character_id=cid)
                .order_by(CharacterRevision.id).all()]


# =============================================================== histórico
def test_edicoes_seguidas_viram_uma_revisao(mesa):
    _, _, cid = mesa_com_ficha(mesa)
    mesa.autosave("ana", cid, version="1", bar__pv__current="15")
    mesa.autosave("ana", cid, version="2", notes="primeira nota")
    mesa.autosave("ana", cid, version="3", attr__agi="3")
    revs = revisions(mesa, cid)
    assert len(revs) == 1
    reason, author, changed, data = revs[0]
    assert (reason, author) == ("edição", "ana")
    assert set(changed) == {"barras", "notas", "atributos"}
    assert data["bars"]["pv"]["current"] == 20          # o estado de ANTES da leva


def test_mudanca_de_outra_pessoa_abre_revisao_propria(mesa):
    camp, _, cid = mesa_com_ficha(mesa)
    mesa.autosave("ana", cid, version="1", notes="x")
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/combate/novo" % camp, data={"name": "C"})
    state = mestre.post("/campanhas/%d/combate/1/adicionar" % camp, json={"party": True}).get_json()
    state["combatants"][0]["hp"] = 7
    mestre.post("/campanhas/%d/combate/1/salvar" % camp, json=state)
    mestre.post("/campanhas/%d/sessoes/nova" % camp, data={"title": "S"})
    mestre.post("/campanhas/%d/sessoes/1/xp" % camp, data={"amount": "100"})
    assert [(r[0], r[1]) for r in revisions(mesa, cid)] == [
        ("edição", "ana"), ("combate", "mestre"), ("xp da sessão", "mestre")]


def test_desfazer_e_desfazer_o_desfazer(mesa):
    _, _, cid = mesa_com_ficha(mesa)
    ana = mesa.user("ana")
    mesa.autosave("ana", cid, version="1", bar__pv__current="3")
    response = ana.post("/fichas/%d/desfazer" % cid, follow_redirects=True)
    assert "Desfeito".encode() in response.data
    assert mesa.sheet(cid).data["bars"]["pv"]["current"] == 20

    ana.post("/fichas/%d/desfazer" % cid)                 # desfaz a restauração
    assert mesa.sheet(cid).data["bars"]["pv"]["current"] == 3


def test_restaurar_uma_revisao_especifica(mesa):
    _, _, cid = mesa_com_ficha(mesa)
    ana = mesa.user("ana")
    ana.post("/fichas/%d" % cid, data={"notes": "versão A"})
    ana.post("/fichas/%d" % cid, data={"__action": "rest:long", "notes": "versão B"})
    ana.post("/fichas/%d" % cid, data={"notes": "versão C"})
    with mesa.app.app_context():
        first = CharacterRevision.query.filter_by(character_id=cid).order_by(CharacterRevision.id).first()
        rid = first.id
    page = ana.get("/fichas/%d/historico" % cid)
    assert page.status_code == 200 and b"Restaurar" in page.data
    ana.post("/fichas/%d/historico/%d/restaurar" % (cid, rid))
    assert mesa.sheet(cid).data["notes"] == ""


def test_historico_so_para_quem_edita(mesa):
    camp, code, cid = mesa_com_ficha(mesa)
    mesa.join("bruno", code)
    mesa.autosave("ana", cid, version="1", notes="segredo do personagem")
    bruno = mesa.user("bruno")
    assert bruno.get("/fichas/%d/historico" % cid).status_code == 403
    assert bruno.post("/fichas/%d/desfazer" % cid).status_code == 403
    assert mesa.user("mestre").get("/fichas/%d/historico" % cid).status_code == 200


def test_historico_guarda_so_as_mais_recentes(mesa):
    from app.extensions import db
    from app.models import Character
    _, _, cid = mesa_com_ficha(mesa)
    with mesa.app.app_context():
        for n in range(70):
            ch = db.session.get(Character, cid)
            ch.data = dict(ch.data, notes="nota %d" % n)
            ch._revision_reason = "teste"
            db.session.commit()
        assert CharacterRevision.query.filter_by(character_id=cid).count() == 60


def test_excluir_ficha_leva_o_historico(mesa):
    _, _, cid = mesa_com_ficha(mesa)
    mesa.autosave("ana", cid, version="1", notes="x")
    mesa.user("ana").post("/fichas/%d/excluir" % cid)
    with mesa.app.app_context():
        assert CharacterRevision.query.count() == 0


# ============================================================ limite de login
def login(client, who, password):
    return client.post("/entrar", data={"identifier": who, "password": password})


def test_cinco_senhas_erradas_bloqueiam_a_conta(mesa):
    mesa.user("ana")
    client = mesa.app.test_client()
    for _ in range(5):
        assert login(client, "ana", "errada").status_code == 401
    blocked = login(client, "ana", "segredo123")          # nem a senha certa passa agora
    assert blocked.status_code == 429 and "Muitas tentativas".encode() in blocked.data
    # o bloqueio é da conta: outra conta, do mesmo IP, continua podendo tentar
    assert login(mesa.app.test_client(), "bruno-inexistente", "x").status_code == 401


def test_bloqueio_expira(mesa):
    from app.extensions import db
    mesa.user("ana")
    client = mesa.app.test_client()
    for _ in range(5):
        login(client, "ana", "errada")
    with mesa.app.app_context():
        for attempt in LoginAttempt.query.all():
            attempt.created_at = datetime.utcnow() - timedelta(minutes=16)
        db.session.commit()
    assert login(client, "ana", "segredo123").status_code == 302


def test_acerto_zera_as_falhas(mesa):
    mesa.user("ana")
    client = mesa.app.test_client()
    for _ in range(4):
        login(client, "ana", "errada")
    assert login(client, "ana", "segredo123").status_code == 302
    client.get("/sair")
    for _ in range(4):
        assert login(client, "ana", "errada").status_code == 401   # contou do zero


def test_mesmo_ip_testando_varias_contas_e_bloqueado(mesa):
    mesa.user("ana")
    client = mesa.app.test_client()
    for n in range(20):
        login(client, "chute%d" % n, "x")
    assert login(client, "ana", "segredo123").status_code == 429


def test_login_por_nome_ignora_maiusculas(mesa):
    client = mesa.app.test_client()
    client.post("/cadastro", data={"username": "Adrinho3677", "email": "a@a.dev",
                                   "password": "segredo123", "confirm": "segredo123"})
    for typed in ("Adrinho3677", "adrinho3677", "ADRINHO3677", "A@A.DEV"):
        fresh = mesa.app.test_client()
        assert login(fresh, typed, "segredo123").status_code == 302, typed

    duplicate = mesa.app.test_client().post("/cadastro", data={
        "username": "adrinho3677", "email": "b@b.dev", "password": "segredo123", "confirm": "segredo123"},
        follow_redirects=True)
    assert "já está em uso".encode() in duplicate.data


def test_login_nao_redireciona_para_fora(mesa):
    mesa.user("ana")
    for evil in ("//evil.com", "https://evil.com", "/\\evil.com", "javascript:alert(1)"):
        client = mesa.app.test_client()
        response = client.post("/entrar?next=" + evil, data={"identifier": "ana", "password": "segredo123"})
        assert response.headers["Location"].endswith("/painel"), evil
    ok = mesa.app.test_client().post("/entrar?next=/fichas/", data={"identifier": "ana", "password": "segredo123"})
    assert ok.headers["Location"].endswith("/fichas/")


def test_atras_de_proxy_usa_o_ip_real(template_db, tmp_path):
    from app import create_app
    path = str(tmp_path / "proxy.db")
    shutil.copy(template_db, path)
    cfg = make_config(path, tmp_path)
    cfg.BEHIND_PROXY = True
    app = create_app(cfg)
    client = app.test_client()
    client.post("/entrar", data={"identifier": "x", "password": "y"},
                headers={"X-Forwarded-For": "forjado, 203.0.113.9"})
    with app.app_context():
        assert LoginAttempt.query.one().ip == "203.0.113.9"   # só o último salto conta


# ========================================================== convite por link
def test_convite_para_quem_nao_tem_conta(mesa):
    camp, code = mesa.campaign("mestre", name="Mata Escura")
    anon = mesa.app.test_client()
    page = anon.get("/campanhas/convite/%s" % code)
    assert page.status_code == 200 and "Mata Escura".encode() in page.data
    assert ("next=/campanhas/convite/" + code).encode() in page.data

    registered = anon.post("/cadastro?next=/campanhas/convite/%s" % code, data={
        "username": "ana", "email": "ana@a.dev", "password": "segredo123", "confirm": "segredo123"})
    assert registered.headers["Location"].endswith("/campanhas/convite/%s" % code)
    with mesa.app.app_context():
        assert CampaignMember.query.filter_by(campaign_id=camp).count() == 1   # ainda não entrou

    anon.post("/campanhas/convite/%s" % code)
    assert anon.get("/campanhas/%d" % camp).status_code == 200


def test_abrir_o_link_nao_entra_sozinho(mesa):
    camp, code = mesa.campaign("mestre")
    ana = mesa.user("ana")
    page = ana.get("/campanhas/convite/%s" % code)
    assert "Entrar na campanha".encode() in page.data
    assert ana.get("/campanhas/%d" % camp).status_code == 403


def test_codigo_novo_invalida_o_link(mesa):
    camp, code = mesa.campaign("mestre")
    mesa.user("mestre").post("/campanhas/%d/mesa/novo-codigo" % camp)
    assert mesa.user("ana").get("/campanhas/convite/%s" % code).status_code == 404


def test_chutar_codigos_e_bloqueado(mesa):
    _, code = mesa.campaign("mestre")
    ana = mesa.user("ana")
    for n in range(20):
        ana.get("/campanhas/convite/ZZZ%03d" % n)
    assert ana.get("/campanhas/convite/%s" % code).status_code == 429
    assert "Muitas tentativas".encode() in ana.post(
        "/campanhas/entrar", data={"invite_code": code}, follow_redirects=True).data


def test_link_aparece_para_o_mestre(mesa):
    camp, code = mesa.campaign("mestre")
    page = mesa.user("mestre").get("/campanhas/%d/mesa" % camp)
    assert ("/campanhas/convite/%s" % code).encode() in page.data


# ================================================================ exportação
def test_exportar_campanha_completa(mesa):
    camp, code, cid = mesa_com_ficha(mesa)
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/anotacoes/nova" % camp, data={"title": "Segredo", "body": "o padre mente",
                                                             "visibility": "mestre"})
    mestre.post("/campanhas/%d/sessoes/nova" % camp, data={"title": "Sessão 1"})
    mestre.post("/campanhas/%d/mapas" % camp, data={"file": png_file(), "title": "Covil"},
                content_type="multipart/form-data")
    mesa.user("ana").post("/fichas/%d/identidade" % cid, data={"name": "Kian", "avatar_file": png_file()},
                          content_type="multipart/form-data")

    response = mestre.get("/campanhas/%d/exportar" % camp)
    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    assert "attachment" in response.headers["Content-Disposition"]
    assert "no-store" in response.headers["Cache-Control"]

    archive = zipfile.ZipFile(io.BytesIO(response.data))
    names = archive.namelist()
    assert "campanha.json" in names and "LEIA-ME.txt" in names
    assert len([n for n in names if n.startswith("imagens/")]) == 2   # mapa + retrato
    doc = json.loads(archive.read("campanha.json"))
    assert doc["formato"] == "grimorio-campanha"
    assert doc["fichas"][0]["nome"] == "Kian" and doc["fichas"][0]["retrato"].startswith("imagens/")
    assert doc["anotacoes"][0]["texto"] == "o padre mente"
    assert doc["sessoes"][0]["titulo"] == "Sessão 1"
    assert {m["usuario"] for m in doc["mesa"]} == {"mestre", "ana"}
    assert b"@teste.dev" not in archive.read("campanha.json")          # nenhum e-mail
    assert doc["sistema"]["dados"]["labels"]["spells"] == "Rituais"


def test_so_o_mestre_exporta(mesa):
    camp, _, _ = mesa_com_ficha(mesa)
    assert mesa.user("ana").get("/campanhas/%d/exportar" % camp).status_code == 403
    assert mesa.user("estranho").get("/campanhas/%d/exportar" % camp).status_code == 403
