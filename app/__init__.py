# -*- coding: utf-8 -*-
import os

from flask import Flask, jsonify, render_template, request
from flask_wtf.csrf import CSRFError

from config import Config
from app.extensions import csrf, db, login_manager, migrate

# Revisão que corresponde exatamente ao esquema que o db.create_all() criava
# antes das migrações existirem. Bancos antigos são marcados nela.
INITIAL_REVISION = "0001_inicial"


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)

    if app.config.get("BEHIND_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix
        # Confia só no último salto (o proxy do PythonAnywhere): um visitante que
        # mande X-Forwarded-For inventado não consegue trocar o próprio IP.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    os.makedirs(os.path.join(os.path.dirname(os.path.dirname(__file__)), "instance"), exist_ok=True)

    db.init_app(app)
    # render_as_batch: o SQLite não sabe alterar colunas com ALTER TABLE;
    # o Alembic recria a tabela por baixo dos panos quando precisa.
    migrate.init_app(app, db, directory=app.config["MIGRATIONS_DIR"], render_as_batch=True)
    csrf.init_app(app)
    login_manager.init_app(app)

    from app import models  # noqa: F401  (registra as tabelas)
    from app import revisions
    from app.presets import sync_presets

    revisions.register()

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(models.User, int(user_id))

    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.main import bp as main_bp
    from app.blueprints.systems import bp as systems_bp
    from app.blueprints.campaigns import bp as campaigns_bp
    from app.blueprints.characters import bp as characters_bp
    from app.blueprints.uploads import bp as uploads_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(systems_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(characters_bp)
    app.register_blueprint(uploads_bp)

    register_filters(app)
    register_errors(app)

    from app.commands import register_commands
    register_commands(app)

    with app.app_context():
        if app.config["AUTO_MIGRATE"]:
            run_migrations(app)
        if _has_table("game_systems"):
            sync_presets(db, models.GameSystem)

    return app


def _has_table(name):
    from sqlalchemy import inspect
    return name in inspect(db.engine).get_table_names()


def run_migrations(app):
    """Deixa o banco na versão mais nova das migrações."""
    from flask_migrate import stamp, upgrade
    from sqlalchemy import inspect

    versions = os.path.join(app.config["MIGRATIONS_DIR"], "versions")
    if not os.path.isdir(versions) or not any(f.endswith(".py") for f in os.listdir(versions)):
        return

    tables = set(inspect(db.engine).get_table_names())
    if tables and "alembic_version" not in tables:
        # Banco criado pelo db.create_all() de antes das migrações: as tabelas
        # já existem, então só registramos em que versão ele está.
        stamp(directory=app.config["MIGRATIONS_DIR"], revision=INITIAL_REVISION)
    upgrade(directory=app.config["MIGRATIONS_DIR"])


def register_filters(app):
    from app.utils import excerpt, local_time, pretty_number, rich_text, signed

    app.jinja_env.filters["rich"] = rich_text
    app.jinja_env.filters["excerpt"] = excerpt
    app.jinja_env.filters["signed"] = signed
    app.jinja_env.filters["number"] = pretty_number
    app.jinja_env.filters["hora"] = local_time

    @app.context_processor
    def inject_globals():
        return {
            "APP_NAME": "Grimório",
            "APP_TAGLINE": "Gerenciador de campanhas de RPG",
        }


def register_errors(app):
    def wants_json():
        return (request.headers.get("X-Requested-With") == "fetch"
                or request.is_json
                or request.accept_mimetypes.best == "application/json")

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        message = "Sua sessão expirou ou o formulário ficou velho. Recarregue a página e tente de novo."
        if wants_json():
            return jsonify({"ok": False, "error": "csrf", "message": message}), 400
        return render_template("errors/error.html", code=400, message=message), 400

    @app.errorhandler(403)
    def forbidden(error):
        if wants_json():
            return jsonify({"ok": False, "error": "forbidden"}), 403
        return render_template("errors/error.html", code=403,
                               message="Você não tem acesso a esta página."), 403

    @app.errorhandler(404)
    def not_found(error):
        if wants_json():
            return jsonify({"ok": False, "error": "not_found"}), 404
        return render_template("errors/error.html", code=404,
                               message="Não encontramos o que você procurava."), 404

    @app.errorhandler(413)
    def too_large(error):
        message = "Arquivo grande demais. O limite é de 4 MB."
        if wants_json():
            return jsonify({"ok": False, "error": "too_large", "message": message}), 413
        return render_template("errors/error.html", code=413, message=message), 413

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        if wants_json():
            return jsonify({"ok": False, "error": "server"}), 500
        return render_template("errors/error.html", code=500,
                               message="Algo deu errado do nosso lado."), 500
