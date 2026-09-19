# -*- coding: utf-8 -*-
"""Diário privado, sessões por aparelho, dados, tabelas, sussurros, atrasar turno,
mapa (tamanho/desfazer), bestiário, combates preparados, lembretes, admin e TV."""
import io
import zipfile
from datetime import date, timedelta

import pytest

from app import dice, tables
from app.models import (Encounter, GameSession, Note, RandomTable, RollLog, User, Whisper)


def mesa_basica(mesa, slug="dnd-5e"):
    camp, code = mesa.campaign("mestre", slug=slug)
    mesa.join("ana", code)
    mesa.join("bia", code)
    kian = mesa.character("ana", camp, name="Kian")
    return camp, code, kian


# ------------------------------------------------------------ diário privado
def test_diario_privado_nem_o_mestre_le(mesa, app):
    camp, _, _ = mesa_basica(mesa)
    ana, mestre = mesa.user("ana"), mesa.user("mestre")
    ana.post("/campanhas/%d/anotacoes/nova" % camp, data={
        "title": "Meu segredo", "body": "desconfio do mestre", "visibility": "privada"})
    with app.app_context():
        note = Note.query.filter_by(title="Meu segredo").one()
        note_id = note.id
        assert note.visibility == "privada"

    assert "Meu segredo" in ana.get("/campanhas/%d/anotacoes" % camp).get_data(as_text=True)
    assert "Meu segredo" not in mestre.get("/campanhas/%d/anotacoes" % camp).get_data(as_text=True)
    assert "Meu segredo" not in mesa.user("bia").get("/campanhas/%d/anotacoes" % camp).get_data(as_text=True)
    base = "/campanhas/%d/anotacoes/%d" % (camp, note_id)
    assert mestre.get(base + "/editar").status_code == 404
    assert mestre.post(base + "/revelar", data={"target": "mesa"}).status_code == 404
    assert mestre.post(base + "/fixar").status_code == 404
    assert mestre.post(base + "/excluir").status_code == 404
    assert mestre.post("/campanhas/%d/mostrar" % camp, data={"kind": "anotacao", "id": note_id}).status_code == 404

    exported = mestre.get("/campanhas/%d/exportar" % camp)
    data = zipfile.ZipFile(io.BytesIO(exported.data)).read("campanha.json").decode("utf-8")
    exported.close()
    assert "desconfio do mestre" not in data


def test_mestre_nao_escolhe_privada_para_nota_de_jogador(mesa, app):
    camp, _, _ = mesa_basica(mesa)
    mesa.user("bia").post("/campanhas/%d/anotacoes/nova" % camp, data={
        "title": "Da mesa", "body": "x", "visibility": "mesa"})
    with app.app_context():
        note_id = Note.query.filter_by(title="Da mesa").one().id
    mesa.user("mestre").post("/campanhas/%d/anotacoes/%d/editar" % (camp, note_id), data={
        "title": "Da mesa", "body": "x", "visibility": "privada"})
    assert mesa.get(Note, note_id).visibility == "mesa"


# ------------------------------------------------------ sair de todos os aparelhos
def test_trocar_senha_desconecta_outros_aparelhos(mesa, app):
    mesa.user("ana")
    celular = app.test_client()
    celular.post("/entrar", data={"identifier": "ana", "password": "segredo123"})
    assert celular.get("/painel").status_code == 200

    ana = mesa.user("ana")
    ana.post("/conta", data={"current": "segredo123", "password": "novasenha9", "confirm": "novasenha9"})
    assert ana.get("/painel").status_code == 200          # este continua
    assert celular.get("/painel").status_code == 302      # o outro saiu

    ana.post("/conta/sair-de-todos")
    assert ana.get("/painel").status_code == 302


def test_cookie_antigo_sem_versao_continua_valendo(mesa, app):
    """Quem estava logado antes da atualização não é derrubado."""
    mesa.user("ana")
    client = app.test_client()
    with app.app_context():
        user_id = User.query.filter_by(username="ana").one().id
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True
    assert client.get("/painel").status_code == 200


# ------------------------------------------------------------------ dados
@pytest.mark.parametrize("formula", ["2d6+3", "1d20+1d4+2", "2d20kh1", "2d20kl1", "4d6kh3", "3d6!",
                                     "d%", "10-1d4"])
def test_formulas_validas(formula):
    result = dice.roll_formula(formula)
    assert isinstance(result["result"], int) and result["detail"]


@pytest.mark.parametrize("formula", ["", "2d6+", "2d6 3", "1d1", "101d6", "abc", "1d20+FOR", "x" * 90])
def test_formulas_invalidas(formula):
    with pytest.raises(dice.DiceError):
        dice.roll_formula(formula)


def test_kh_fica_com_o_maior_e_explosao_tem_limite():
    for _ in range(50):
        result = dice.roll_formula("4d6kh3")
        kept = [int(x) for x in result["detail"].split("[")[1].rstrip("]").split(", ") if not x.startswith("(")]
        assert len(kept) == 3 and result["result"] == sum(kept)
    result = dice.roll_formula("100d2!")  # explode muito, mas para
    assert result["result"] <= 100 * 2 + dice.MAX_EXPLOSIONS * 2


def test_sigla_da_ficha_e_vantagem(mesa):
    cid = mesa.character("ana", slug="dnd-5e")
    client = mesa.user("ana")
    roll = client.post("/fichas/%d/rolar" % cid, json={"formula": "1d20+FOR"}).get_json()["roll"]
    assert "FOR(0)" in roll["detail"]  # FOR 10 em D&D = modificador 0
    roll = client.post("/fichas/%d/rolar" % cid, json={"dice": 1, "bonus": 2, "mode": "vantagem"}).get_json()["roll"]
    assert "vantagem" in roll["detail"]


# ------------------------------------------------------- tabelas aleatórias
def test_tabela_parse():
    entries = tables.parse("1-3: Lobos\n4: Bandidos\nChuva\n\n6-8: Nada")
    assert [(e["min"], e["max"]) for e in entries] == [(1, 3), (4, 4), (5, 5), (6, 8)]
    assert tables.die_size(entries) == 8
    for bad in ("", "1-3: A\n2: B", "5-2: X", "1-2000: X"):
        with pytest.raises(tables.TableError):
            tables.parse(bad)
    assert tables.as_text(entries).splitlines()[0] == "1-3: Lobos"


def test_tabelas_mestre_e_mesa(mesa, app):
    camp, _, _ = mesa_basica(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    url = "/campanhas/%d/tabelas" % camp
    mestre.post(url, data={"name": "Encontros", "entries": "1-2: Lobos\n3: Nada", "visibility": "mestre"})
    mestre.post(url, data={"name": "Clima", "entries": "Sol\nChuva", "visibility": "mesa"})
    assert ana.post(url, data={"name": "Minha", "entries": "x"}).status_code == 403
    assert mestre.post(url, data={"name": "Ruim", "entries": "1-3: A\n2: B"}).status_code == 400
    with app.app_context():
        secret_id = RandomTable.query.filter_by(name="Encontros").one().id
        public_id = RandomTable.query.filter_by(name="Clima").one().id

    page = ana.get(url).get_data(as_text=True)
    assert "Clima" in page and "Encontros" not in page and "Lobos" not in page
    assert ana.post("%s/%d/rolar" % (url, secret_id), json={}).status_code == 404

    result = ana.post("%s/%d/rolar" % (url, public_id), json={}).get_json()
    assert result["text"] in ("Sol", "Chuva")
    secret = mestre.post("%s/%d/rolar" % (url, secret_id), json={}).get_json()
    with app.app_context():
        assert RollLog.query.filter_by(label="📜 Encontros").one().secret is True
    feed = [r["label"] for r in ana.get("/campanhas/%d/rolagens" % camp).get_json()["rolls"]]
    assert "📜 Clima" in feed and "📜 Encontros" not in feed
    assert secret["value"] in (1, 2, 3)


# ------------------------------------------------------------------ sussurros
def test_sussurros_so_entre_os_dois(mesa, app):
    camp, _, _ = mesa_basica(mesa)
    mestre, ana, bia = mesa.user("mestre"), mesa.user("ana"), mesa.user("bia")
    url = "/campanhas/%d/sussurro" % camp
    assert ana.post(url, json={"text": "roubo a chave"}).status_code == 200
    assert ana.post(url, json={"text": "  "}).status_code == 400
    with app.app_context():
        w = Whisper.query.one()
        assert w.recipient.username == "mestre"
        bia_id = User.query.filter_by(username="bia").one().id
        mestre_id = User.query.filter_by(username="mestre").one().id
    assert mestre.post(url, json={"text": "ok", "to": bia_id}).status_code == 200
    assert mestre.post(url, json={"text": "ok", "to": mestre_id}).status_code == 400

    live = lambda c: c.get("/campanhas/%d/ao-vivo?s=whispers::" % camp).get_json()["sections"]["whispers:"]["data"]
    assert [w["text"] for w in live(ana)["items"]] == ["roubo a chave"]
    assert [w["text"] for w in live(bia)["items"]] == ["ok"]
    master_view = live(mestre)
    assert len(master_view["items"]) == 2 and {p["name"] for p in master_view["people"]} == {"ana", "bia"}
    assert "people" not in live(ana)


# -------------------------------------------------------------- atrasar turno
def test_atrasar_turno_fica_salvo(mesa):
    camp, _, _ = mesa_basica(mesa)
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/combate/novo" % camp, data={"name": "C"})
    base = "/campanhas/%d/combate/1" % camp
    mestre.post(base + "/adicionar", json={"party": True})
    state = mestre.get(base + "/estado").get_json()
    state["combatants"][0]["delayed"] = True
    saved = mestre.post(base + "/salvar", json=state).get_json()
    assert saved["combatants"][0]["delayed"] is True
    assert mesa.user("ana").get(base + "/estado").get_json()["combatants"][0]["delayed"] is True


# --------------------------------------------- mapa: tamanho, deslocamento, desfazer
def mapa(mesa):
    camp, _, kian = mesa_basica(mesa)
    mestre = mesa.user("mestre")
    ghoul = mesa.character("mestre", camp, name="Ogro", kind="criatura")
    mestre.post("/campanhas/%d/combate/novo" % camp, data={"name": "C"})
    base = "/campanhas/%d/combate/1" % camp
    mestre.post(base + "/adicionar", json={"party": True})
    state = mestre.post(base + "/adicionar", json={"character_id": ghoul}).get_json()
    uids = {c["name"]: c["uid"] for c in state["combatants"]}
    return camp, base, uids, kian


def test_criatura_grande_e_borda(mesa):
    camp, base, uids, _ = mapa(mesa)
    mestre = mesa.user("mestre")
    mestre.post(base + "/mapa/mover", json={"uid": uids["Ogro 1"], "x": 19, "y": 13})
    state = mestre.post(base + "/mapa/esconder", json={"uid": uids["Ogro 1"], "size": 2}).get_json()
    ogro = [t for t in state["tokens"] if t["name"] == "Ogro 1"][0]
    assert (ogro["size"], ogro["x"], ogro["y"]) == (2, 18, 12)  # empurrado para caber
    assert mestre.post(base + "/mapa/mover", json={"uid": uids["Ogro 1"], "x": 19, "y": 0}).status_code == 400
    assert mesa.user("ana").post(base + "/mapa/esconder", json={"uid": uids["Ogro 1"], "size": 3}).status_code == 403


def test_deslocamento_da_ficha_vira_quadrados(mesa, app):
    from app.extensions import db
    from app.models import Character
    camp, base, uids, kian = mapa(mesa)
    with app.app_context():
        ch = db.session.get(Character, kian)
        data = dict(ch.data)
        data["meta"] = dict(data.get("meta") or {}, deslocamento="9 m")
        ch.data = data
        db.session.commit()
    mesa.user("mestre").post(base + "/mapa/mover", json={"uid": uids["Kian"], "x": 1, "y": 1})
    token = mesa.user("ana").get(base + "/mapa").get_json()["tokens"][0]
    assert token["speed"] == 6  # 9 m ÷ 1,5 m


def test_desfazer_movimento(mesa):
    camp, base, uids, _ = mapa(mesa)
    mestre, ana = mesa.user("mestre"), mesa.user("ana")
    ana.post(base + "/mapa/mover", json={"uid": uids["Kian"], "x": 1, "y": 1})
    ana.post(base + "/mapa/mover", json={"uid": uids["Kian"], "x": 4, "y": 1})
    mestre.post(base + "/mapa/mover", json={"uid": uids["Ogro 1"], "x": 8, "y": 8})

    state = ana.post(base + "/mapa/desfazer", json={}).get_json()  # desfaz o dela, não o do mestre
    pos = {t["name"]: (t["x"], t["y"]) for t in state["tokens"]}
    assert pos == {"Kian": (1, 1), "Ogro 1": (8, 8)}
    state = ana.post(base + "/mapa/desfazer", json={}).get_json()
    assert [t["name"] for t in state["tokens"]] == ["Ogro 1"]  # voltou para "na mão"
    assert ana.post(base + "/mapa/desfazer", json={}).status_code == 400  # nada mais dela

    state = mestre.post(base + "/mapa/desfazer", json={}).get_json()
    assert state["tokens"] == []


# --------------------------------------------------------------- bestiário
def test_copiar_do_bestiario_de_outra_campanha(mesa, app):
    camp, _, _ = mesa_basica(mesa)
    mestre = mesa.user("mestre")
    antiga, _ = mesa.campaign("mestre", slug="dnd-5e", name="Antiga")
    lobo = mesa.character("mestre", antiga, name="Lobo terrível", kind="criatura")
    outra_sistema, _ = mesa.campaign("mestre", slug="tormenta-20", name="T20")
    goblin = mesa.character("mestre", outra_sistema, name="Goblin", kind="criatura")

    page = mestre.get("/campanhas/%d/elenco" % camp).get_data(as_text=True)
    assert "Lobo terrível" in page and "Goblin" not in page
    mestre.post("/campanhas/%d/elenco/copiar" % camp, data={"character_id": lobo})
    with app.app_context():
        from app.models import Character
        copies = Character.query.filter_by(name="Lobo terrível").all()
        assert {c.campaign_id for c in copies} == {antiga, camp}
    bad = mestre.post("/campanhas/%d/elenco/copiar" % camp, data={"character_id": goblin}, follow_redirects=True)
    assert "outro sistema" in bad.get_data(as_text=True)
    # Ficha de outro mestre não se copia.
    alheia, _ = mesa.campaign("outro", slug="dnd-5e", name="Alheia")
    npc = mesa.character("outro", alheia, name="Segredo alheio", kind="npc")
    assert mestre.post("/campanhas/%d/elenco/copiar" % camp, data={"character_id": npc}).status_code == 404


# ------------------------------------------------------- combates preparados
def test_combate_preparado_na_sessao(mesa, app):
    camp, _, _ = mesa_basica(mesa)
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/sessoes/nova" % camp, data={"title": "A ponte"})
    with app.app_context():
        sid = GameSession.query.filter_by(campaign_id=camp).one().id
    mestre.post("/campanhas/%d/sessoes/%d/combate" % (camp, sid), data={"name": "Emboscada na ponte"})
    page = mestre.get("/campanhas/%d/sessoes/%d" % (camp, sid)).get_data(as_text=True)
    assert "Emboscada na ponte" in page
    assert "preparado para a sessão" in mestre.get("/campanhas/%d/combate" % camp).get_data(as_text=True)
    assert mesa.user("ana").post("/campanhas/%d/sessoes/%d/combate" % (camp, sid), data={}).status_code == 403

    mestre.post("/campanhas/%d/sessoes/%d/excluir" % (camp, sid))
    with app.app_context():
        encounter = Encounter.query.filter_by(name="Emboscada na ponte").one()
        assert encounter.session_id is None  # o combate fica, só perde o vínculo


# ------------------------------------------------------------------ lembretes
def sessao_amanha(mesa, app, camp):
    from app.extensions import db
    mesa.user("mestre").post("/campanhas/%d/sessoes/nova" % camp, data={"title": "Amanhã"})
    with app.app_context():
        item = GameSession.query.filter_by(campaign_id=camp).one()
        item.scheduled_for = date.today() + timedelta(days=1)
        item.start_time = "19:30"
        db.session.commit()
        return item.id


def test_lembrete_no_painel_e_resposta(mesa, app):
    camp, _, _ = mesa_basica(mesa)
    sid = sessao_amanha(mesa, app, camp)
    ana = mesa.user("ana")
    painel = ana.get("/painel").get_data(as_text=True)
    assert "é amanhã às 19:30. Você vai?" in painel
    assert "Você vai?" not in mesa.user("mestre").get("/painel").get_data(as_text=True)
    ana.post("/campanhas/%d/sessoes/%d/presenca" % (camp, sid), data={"status": "vou", "next": "/painel"})
    assert "Você vai?" not in ana.get("/painel").get_data(as_text=True)


def test_lembrete_por_email_com_link_de_presenca(mesa, app):
    import re
    camp, _, _ = mesa_basica(mesa)
    sid = sessao_amanha(mesa, app, camp)
    app.config["SITE_URL"] = "https://grimorio.exemplo"
    from app import reminders
    with app.test_request_context():
        assert reminders.send_due() == 2           # ana e bia
        assert reminders.send_due() == 0           # não repete
    outbox = app.extensions["outbox"]
    message = [m for m in outbox if m["to"] == "ana@teste.dev"][0]
    link = re.search(r"https://grimorio\.exemplo(\S+)\?resposta=vou", message["body"]).group(1)

    anonymous = app.test_client()
    page = anonymous.get(link)  # abrir só mostra a pergunta
    assert page.status_code == 200
    with app.app_context():
        from app.extensions import db
        assert db.session.get(GameSession, sid).attendance.count() == 0
    anonymous.post(link, data={"status": "vou"})
    with app.app_context():
        from app.extensions import db
        answers = {a.user.username: a.status for a in db.session.get(GameSession, sid).attendance}
        assert answers == {"ana": "vou"}
    assert anonymous.get(link[:-4] + "xxxx", follow_redirects=False).status_code == 302


def test_sem_email_nao_manda_nada(mesa, app):
    camp, _, _ = mesa_basica(mesa)
    sessao_amanha(mesa, app, camp)
    from app import reminders
    app.testing = False
    try:
        with app.test_request_context():
            assert reminders.send_due() == 0
    finally:
        app.testing = True


# ------------------------------------------------------------------ admin
def test_admin_e_a_primeira_conta(mesa, app):
    mesa.user("dono")
    mesa.user("visitante")
    assert mesa.user("dono").get("/admin/").status_code == 200
    assert mesa.user("visitante").get("/admin/").status_code == 404
    app.config["ADMIN_USERNAMES"] = "visitante"
    assert mesa.user("visitante").get("/admin/").status_code == 200
    assert mesa.user("dono").get("/admin/").status_code == 404


def test_admin_senha_temporaria(mesa, app):
    mesa.user("dono")
    mesa.user("ana")
    with app.app_context():
        ana_id = User.query.filter_by(username="ana").one().id
    page = mesa.user("dono").post("/admin/usuarios/%d/senha" % ana_id, follow_redirects=True).get_data(as_text=True)
    import re
    temporary = re.search(r"Senha temporária de ana: (\S+) —", page).group(1)
    assert mesa.user("ana").get("/painel").status_code == 302  # derrubada
    ok = app.test_client().post("/entrar", data={"identifier": "ana", "password": temporary})
    assert ok.status_code == 302


def test_erro_500_fica_registrado(mesa, app):
    from app.models import ErrorReport

    @app.route("/_quebra")
    def quebra():
        raise ValueError("de propósito")
    mesa.user("dono")
    app.testing = False
    app.config["PROPAGATE_EXCEPTIONS"] = False
    try:
        client = app.test_client()
        assert client.get("/_quebra").status_code == 500
        assert client.get("/_quebra").status_code == 500
    finally:
        app.testing = True
    with app.app_context():
        report = ErrorReport.query.one()
        assert report.count == 2 and "de propósito" in report.summary and report.path == "/_quebra"
    page = mesa.user("dono").get("/admin/").get_data(as_text=True)
    assert "de propósito" in page


def test_limpeza_e_backup(mesa, app):
    import os
    import time
    from app import maintenance
    mesa.user("dono")
    cid = mesa.character("dono")
    client = mesa.user("dono")
    from tests.conftest import png_file
    client.post("/fichas/%d/identidade" % cid, data={"name": "K", "avatar_file": png_file()},
                content_type="multipart/form-data")
    client.post("/fichas/%d/identidade" % cid, data={"name": "K", "avatar_url": "https://x/y.png"})
    folder = app.config["UPLOAD_DIR"]
    orphan = os.path.join(folder, "sobra.png")
    open(orphan, "wb").write(b"x" * 100)
    old = time.time() - 3 * 86400
    for name in os.listdir(folder):
        os.utime(os.path.join(folder, name), (old, old))
    with app.app_context():
        from app.extensions import db
        from app.models import Asset
        for asset in Asset.query.all():
            asset.created_at = asset.created_at - timedelta(days=3)
        db.session.commit()
        preview = maintenance.cleanup(dry_run=True)
        assert preview["files"] >= 1 and os.path.exists(orphan)
        result = maintenance.cleanup()
    assert not os.path.exists(orphan) and result["files"] == preview["files"]

    response = client.get("/admin/backup")
    assert response.status_code == 200 and response.mimetype == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(response.data)).namelist()
    response.close()
    assert "rpgmanager.db" in names
    with app.app_context():
        assert maintenance.days_since_backup_download() == 0


def test_comando_manutencao(mesa, app):
    mesa.user("dono")
    result = app.test_cli_runner().invoke(args=["manutencao"])
    assert result.exit_code == 0, result.output
    assert "Backup:" in result.output and "Limpeza:" in result.output


# ------------------------------------------------------------------ TV
def test_tela_da_tv_mostra_a_visao_da_mesa(mesa):
    camp, base, uids, _ = mapa(mesa)
    mestre = mesa.user("mestre")
    mestre.post(base + "/mapa/mover", json={"uid": uids["Ogro 1"], "x": 5, "y": 5})
    mestre.post(base + "/mapa/esconder", json={"uid": uids["Ogro 1"], "hidden": True})
    mestre.post("/campanhas/%d/relogios" % camp, json={"title": "Só meu", "visibility": "mestre"})
    mestre.post("/campanhas/%d/rolar" % camp, json={"formula": "1d20", "label": "Secreta", "secret": True})

    page = mestre.get("/campanhas/%d/tv" % camp).get_data(as_text=True)
    assert "Ogro 1" not in page and "Só meu" not in page
    live = mestre.get("/campanhas/%d/ao-vivo?s=board:1.mesa:,enc:1.mesa:,clocks:mesa:,rolls:mesa:" % camp)
    sections = live.get_json()["sections"]
    text = str(sections)
    assert "Ogro 1" not in text and "Só meu" not in text and "Secreta" not in text
    # Sem ".mesa", o mestre continua vendo tudo.
    full = str(mestre.get("/campanhas/%d/ao-vivo?s=board:1:,rolls::" % camp).get_json())
    assert "Ogro 1" in full and "Secreta" in full


# ------------------------------------------------- manutenção automática
def test_manutencao_roda_sozinha_uma_vez_por_dia(mesa, app):
    import os
    from datetime import datetime
    from app import maintenance
    mesa.user("dono")
    app.config["AUTO_MAINTENANCE"] = True
    backups = app.config["BACKUP_DIR"]
    client = app.test_client()

    response = client.get("/entrar")
    response.close()  # a manutenção roda quando a resposta termina de sair
    assert len(os.listdir(backups)) == 1
    with app.app_context():
        first = maintenance.last_run()
        assert first is not None
        from app.models import SiteSetting
        assert "Backup:" in SiteSetting.get("manutencao_relatorio")

    client.get("/entrar").close()  # no mesmo dia: não roda de novo
    assert len(os.listdir(backups)) == 1

    with app.app_context():
        # Só uma requisição "ganha" a vez, mesmo chegando juntas.
        from app.extensions import db
        SiteSetting.put(maintenance.LAST_RUN_KEY, (datetime.utcnow() - timedelta(days=2)).isoformat())
        db.session.commit()
        assert maintenance.claim_daily_run() is True
        assert maintenance.claim_daily_run() is False


def test_manutencao_pelo_admin(mesa, app):
    mesa.user("dono")
    page = mesa.user("dono").post("/admin/manutencao", follow_redirects=True).get_data(as_text=True)
    assert "Manutenção feita" in page and "Backup:" in page
