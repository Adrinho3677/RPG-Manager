# -*- coding: utf-8 -*-
"""CSRF, cookies, conta, comandos de administração e migrações."""
import os
import sqlite3

from tests.conftest import csrf_from, make_config


def test_post_sem_token_csrf_e_recusado(csrf_app):
    client = csrf_app.test_client()
    page = client.get("/cadastro")
    token = csrf_from(page.data)

    sem = client.post("/cadastro", data={"username": "ana", "email": "a@a.dev",
                                         "password": "segredo123", "confirm": "segredo123"})
    assert sem.status_code == 400

    com = client.post("/cadastro", data={"username": "ana", "email": "a@a.dev",
                                         "password": "segredo123", "confirm": "segredo123",
                                         "csrf_token": token})
    assert com.status_code == 302


def test_fetch_sem_token_recebe_json(csrf_app):
    client = csrf_app.test_client()
    token = csrf_from(client.get("/cadastro").data)
    client.post("/cadastro", data={"username": "ana", "email": "a@a.dev", "password": "segredo123",
                                   "confirm": "segredo123", "csrf_token": token})
    response = client.post("/campanhas/1/rolar", json={"formula": "1d6"},
                           headers={"X-Requested-With": "fetch"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "csrf"


def test_rota_destrutiva_exige_token(csrf_app):
    """O ataque que o CSRF impede: outro site fazendo o mestre apagar a campanha."""
    client = csrf_app.test_client()
    token = csrf_from(client.get("/cadastro").data)
    client.post("/cadastro", data={"username": "mestre", "email": "m@a.dev", "password": "segredo123",
                                   "confirm": "segredo123", "csrf_token": token})
    token = csrf_from(client.get("/campanhas/nova").data)
    client.post("/campanhas/nova", data={"name": "Alvo", "system_id": 1, "csrf_token": token})
    ataque = client.post("/campanhas/1/excluir")
    assert ataque.status_code == 400
    assert client.get("/campanhas/1").status_code == 200


def test_cookies_de_sessao_endurecidos(app):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["REMEMBER_COOKIE_SAMESITE"] == "Lax"


def test_troca_de_senha(mesa):
    client = mesa.user("ana")
    errada = client.post("/conta", data={"current": "outra", "password": "novasenha", "confirm": "novasenha"},
                         follow_redirects=True)
    assert "não confere".encode() in errada.data
    certa = client.post("/conta", data={"current": "segredo123", "password": "novasenha",
                                        "confirm": "novasenha"})
    assert certa.status_code == 302
    novo = mesa.app.test_client()
    assert novo.post("/entrar", data={"identifier": "ana", "password": "novasenha"}).status_code == 302


def test_comando_redefinir_senha(mesa):
    mesa.user("ana")
    runner = mesa.app.test_cli_runner()
    result = runner.invoke(args=["redefinir-senha", "ana"])
    assert result.exit_code == 0, result.output
    temporaria = result.output.split("Senha temporária: ")[1].split()[0]
    client = mesa.app.test_client()
    assert client.post("/entrar", data={"identifier": "ana", "password": temporaria}).status_code == 302

    missing = runner.invoke(args=["redefinir-senha", "ninguem"])
    assert missing.exit_code != 0 and "não encontrado" in missing.output


def test_comando_backup_mantem_so_os_recentes(mesa):
    mesa.character("ana")
    runner = mesa.app.test_cli_runner()
    folder = mesa.app.config["BACKUP_DIR"]
    for _ in range(5):
        result = runner.invoke(args=["backup"])
        assert result.exit_code == 0, result.output
    files = sorted(f for f in os.listdir(folder) if f.endswith(".db"))
    assert len(files) == 3  # BACKUP_KEEP=3, mesmo com os 5 no mesmo segundo

    newest = max((os.path.join(folder, f) for f in files), key=os.path.getmtime)
    copia = sqlite3.connect(newest)
    assert copia.execute("select count(*) from characters").fetchone()[0] == 1
    copia.close()


# ----------------------------------------------------------------- migrações
def test_banco_legado_e_marcado_e_atualizado(tmp_path):
    """Banco criado pelo db.create_all() de antes das migrações, com dados."""
    from flask_migrate import upgrade
    from app import create_app
    from app.extensions import db

    path = str(tmp_path / "legado.db")
    cfg = make_config(path, tmp_path)
    cfg.AUTO_MIGRATE = False
    app = create_app(cfg)
    with app.app_context():
        upgrade(directory=app.config["MIGRATIONS_DIR"], revision="0001_inicial")
        db.session.execute(db.text("drop table alembic_version"))
        db.session.execute(db.text(
            "insert into users (username, email, password_hash) values ('velho', 'v@v.dev', 'x')"))
        db.session.execute(db.text(
            "insert into game_systems (name, slug, is_preset, data) values ('S', 's', 0, '{}')"))
        db.session.execute(db.text(
            "insert into characters (name, kind, owner_id, system_id, data) values ('Antigo', 'pj', 1, 1, '{}')"))
        db.session.commit()

    cfg.AUTO_MIGRATE = True
    app = create_app(cfg)
    with app.app_context():
        from alembic.script import ScriptDirectory
        config = app.extensions["migrate"].migrate.get_config(app.config["MIGRATIONS_DIR"])
        head = ScriptDirectory.from_config(config).get_current_head()
        version = db.session.execute(db.text("select version_num from alembic_version")).scalar()
        assert version == head   # a mais nova, seja qual for — não fixa o número aqui
        row = db.session.execute(db.text("select name, version from characters")).one()
        assert row == ("Antigo", 1)


def test_esquema_bate_com_os_modelos(app):
    """Nenhuma mudança de modelo ficou sem migração."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.extensions import db

    with app.app_context():
        with db.engine.connect() as connection:
            context = MigrationContext.configure(connection)
            diff = compare_metadata(context, db.metadata)
    assert diff == []
