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
    app.request_class = GrimorioRequest
    app.config.from_object(config_class)
    check_secret_key(app)

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
        # "id:versão". A versão sobe ao trocar a senha ou pedir "sair de todos os
        # aparelhos", e aí os cookies antigos param de valer. Cookie sem versão
        # (de antes disso existir) vale enquanto a conta estiver na versão 0.
        raw_id, _, version = str(user_id).partition(":")
        try:
            user = db.session.get(models.User, int(raw_id))
        except ValueError:
            return None
        if user is None or int(version or 0) != (user.session_version or 0):
            return None
        return user

    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.main import bp as main_bp
    from app.blueprints.systems import bp as systems_bp
    from app.blueprints.campaigns import bp as campaigns_bp
    from app.blueprints.characters import bp as characters_bp
    from app.blueprints.uploads import bp as uploads_bp
    from app.blueprints.live import bp as live_bp
    from app.blueprints.table import bp as table_bp
    from app.blueprints.admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(systems_bp)
    app.register_blueprint(campaigns_bp)
    app.register_blueprint(characters_bp)
    app.register_blueprint(uploads_bp)
    app.register_blueprint(live_bp)
    app.register_blueprint(table_bp)
    app.register_blueprint(admin_bp)

    register_filters(app)
    register_errors(app)
    register_security_headers(app)
    register_static_versions(app)
    from app.maintenance import register_daily
    register_daily(app)

    from app.commands import register_commands
    register_commands(app)

    with app.app_context():
        if app.config["AUTO_MIGRATE"]:
            run_migrations(app)
        if _has_table("game_systems"):
            sync_presets(db, models.GameSystem)

    return app


class GrimorioRequest(Flask.request_class):
    """Limite de upload maior só onde precisa: importar uma campanha (ZIP com
    todos os mapas). No resto do site continua o MAX_CONTENT_LENGTH normal."""

    BIG_UPLOADS = ("campaigns.import_campaign",)

    @property
    def max_content_length(self):
        from flask import current_app
        if self.url_rule is not None and self.endpoint in self.BIG_UPLOADS:
            return current_app.config.get("IMPORT_MAX_BYTES")
        return current_app.config.get("MAX_CONTENT_LENGTH")


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


def check_secret_key(app):
    """Em produção (cookies seguros ligados), a chave padrão é pública — está no
    GitHub. Melhor o site não subir do que subir com sessões falsificáveis."""
    key = app.config.get("SECRET_KEY")
    if app.config.get("SESSION_COOKIE_SECURE") and (
            not key or key == app.config.get("DEFAULT_SECRET_KEY") or len(key) < 16):
        raise RuntimeError(
            "SECRET_KEY não configurada (ou curta demais). No PythonAnywhere, defina "
            "os.environ['SECRET_KEY'] no arquivo WSGI com uma chave longa e aleatória."
        )


def register_static_versions(app):
    """url_for('static', ...) ganha ?v=<data do arquivo>.

    Sem isso o navegador pode continuar usando um sheet.js antigo do cache
    depois de um deploy (o PythonAnywhere não manda Cache-Control). Com a data
    na URL, arquivo mudou = URL nova = download novo.
    """
    @app.url_defaults
    def static_version(endpoint, values):
        if endpoint != "static" or "filename" not in values or "v" in values:
            return
        try:
            values["v"] = int(os.stat(os.path.join(app.static_folder, values["filename"])).st_mtime)
        except OSError:
            pass


def register_security_headers(app):
    @app.after_request
    def security_headers(response):
        # Outro site não pode carregar o Grimório num <iframe> invisível e enganar
        # o usuário para clicar em "excluir" (clickjacking).
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # Links externos não recebem a URL de onde a pessoa veio — ela pode
        # conter o código de convite da campanha.
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response


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
        limit = (app.config.get("IMPORT_MAX_BYTES")
                 if request.endpoint in GrimorioRequest.BIG_UPLOADS else app.config.get("MAX_CONTENT_LENGTH"))
        message = "Arquivo grande demais. O limite é de %d MB." % ((limit or 0) // (1024 * 1024))
        if wants_json():
            return jsonify({"ok": False, "error": "too_large", "message": message}), 413
        return render_template("errors/error.html", code=413, message=message), 413

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        from app import maintenance
        maintenance.record_error(getattr(error, "original_exception", None) or error)
        if wants_json():
            return jsonify({"ok": False, "error": "server"}), 500
        return render_template("errors/error.html", code=500,
                               message="Algo deu errado do nosso lado."), 500
