# -*- coding: utf-8 -*-
import hashlib
import hmac

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from app import mail
from app import security
from app.extensions import db
from app.models import User
from app.utils import valid_email

bp = Blueprint("auth", __name__)

# Para usuário inexistente também gastamos o tempo de conferir uma senha: se só
# conferíssemos quando o usuário existe, o tempo de resposta diria quais nomes
# estão cadastrados.
_DUMMY_HASH = generate_password_hash("senha-que-nao-existe")


def find_user(identifier):
    identifier = (identifier or "").strip().lower()
    return User.query.filter(
        (User.email == identifier) | (db.func.lower(User.username) == identifier)
    ).first()


@bp.route("/entrar", methods=["GET", "POST"])
def login():
    destination = security.safe_next(request.args.get("next"), url_for("main.dashboard"))
    if current_user.is_authenticated:
        return redirect(destination)

    if request.method == "POST":
        identifier = (request.form.get("identifier") or "").strip().lower()
        password = request.form.get("password") or ""
        ip = security.client_ip()

        wait = security.seconds_blocked(identifier, ip)
        if wait:
            security.log_block("login", identifier, ip)
            flash(security.wait_message(wait), "error")
            return render_template("auth/login.html", identifier=identifier), 429

        user = find_user(identifier)
        ok = user.check_password(password) if user else check_password_hash(_DUMMY_HASH, password)
        security.record_attempt(identifier, ip, success=bool(user and ok))
        if user and ok:
            login_user(user, remember=bool(request.form.get("remember")))
            return redirect(destination)
        flash("Usuário ou senha inválidos.", "error")
        return render_template("auth/login.html", identifier=identifier), 401

    return render_template("auth/login.html")


@bp.route("/cadastro", methods=["GET", "POST"])
def register():
    destination = security.safe_next(request.args.get("next"), url_for("main.dashboard"))
    if current_user.is_authenticated:
        return redirect(destination)

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""

        errors = []
        if len(username) < 3:
            errors.append("O nome de usuário precisa de pelo menos 3 caracteres.")
        if len(username) > 64 or "@" in username:
            errors.append("O nome de usuário não pode ter @ nem passar de 64 caracteres.")
        if not valid_email(email):
            errors.append("Informe um e-mail válido (ex.: nome@gmail.com).")
        if len(password) < 6:
            errors.append("A senha precisa de pelo menos 6 caracteres.")
        if password != confirm:
            errors.append("As senhas não conferem.")
        # "Ana" e "ana" seriam a mesma pessoa no login: não deixa cadastrar as duas.
        if User.query.filter(db.func.lower(User.username) == username.lower()).first():
            errors.append("Este nome de usuário já está em uso.")
        if User.query.filter_by(email=email).first():
            errors.append("Este e-mail já está cadastrado.")

        if errors:
            for message in errors:
                flash(message, "error")
            return render_template("auth/register.html", username=username, email=email)

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Conta criada! Bem-vindo à mesa.", "success")
        return redirect(destination)

    return render_template("auth/register.html")


# ------------------------------------------------------ recuperar a senha
RESET_MAX_AGE = 3600  # o link vale 1 hora
RESET_SALT = "redefinir-senha"


def _reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=RESET_SALT)


def _password_fingerprint(user):
    """Muda quando a senha muda: o link só funciona uma vez."""
    return hashlib.sha256(user.password_hash.encode("utf-8")).hexdigest()[:16]


def reset_token(user):
    return _reset_serializer().dumps({"u": user.id, "h": _password_fingerprint(user)})


def user_from_token(token):
    try:
        data = _reset_serializer().loads(token, max_age=RESET_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(User, data.get("u")) if isinstance(data, dict) else None
    if user is None or not hmac.compare_digest(_password_fingerprint(user), str(data.get("h"))):
        return None
    return user


@bp.route("/esqueci-senha", methods=["GET", "POST"])
def forgot():
    """Pede o link por e-mail. A resposta é sempre a mesma, exista a conta ou não."""
    if current_user.is_authenticated:
        return redirect(url_for("auth.account"))
    if request.method == "POST" and mail.enabled():
        email = (request.form.get("email") or "").strip().lower()
        ip = security.client_ip()
        key, ip_key = "reset:" + email[:150], "reset:" + ip
        wait = security.seconds_blocked(key, ip_key, max_account=3, max_ip=10)
        if wait:
            security.log_block("recuperação de senha", email, ip)
            flash(security.wait_message(wait), "error")
            return render_template("auth/forgot.html", mail_enabled=True), 429
        security.record_attempt(key, ip_key, success=False)  # conta para o limite
        user = User.query.filter_by(email=email).first() if valid_email(email) else None
        if user is not None:
            base = current_app.config.get("SITE_URL") or request.host_url.rstrip("/")
            link = base + url_for("auth.reset", token=reset_token(user))
            mail.send(user.email, "Grimório: redefinir sua senha", RESET_EMAIL % {
                "user": user.username, "link": link, "minutes": RESET_MAX_AGE // 60})
        flash("Se houver uma conta com esse e-mail, mandamos um link para criar uma senha nova. "
              "Confira também a caixa de spam.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html", mail_enabled=mail.enabled())


@bp.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def reset(token):
    user = user_from_token(token)
    if user is None:
        flash("Este link não vale mais (passou de 1 hora ou já foi usado). Peça outro.", "error")
        return redirect(url_for("auth.forgot"))
    if request.method == "POST":
        new = request.form.get("password") or ""
        if len(new) < 6:
            flash("A senha nova precisa de pelo menos 6 caracteres.", "error")
        elif new != (request.form.get("confirm") or ""):
            flash("As senhas não conferem.", "error")
        else:
            user.set_password(new)
            user.end_other_sessions()  # quem estava logado com a senha antiga sai
            db.session.commit()
            # Sucesso limpa as tentativas erradas desta conta: quem estava
            # bloqueado por errar a senha consegue entrar agora.
            security.record_attempt(user.username.lower(), security.client_ip(), success=True)
            security.record_attempt(user.email, security.client_ip(), success=True)
            flash("Senha trocada. Entre com a senha nova.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", user=user)


RESET_EMAIL = """Olá, %(user)s!

Alguém (provavelmente você) pediu para redefinir a senha da sua conta no Grimório.
Para criar uma senha nova, abra este link:

%(link)s

O link vale %(minutes)d minutos e funciona uma vez só. Se não foi você, é só ignorar
este e-mail: sua senha continua a mesma.
"""


@bp.route("/conta", methods=["GET", "POST"])
@login_required
def account():
    """Troca de senha. É aqui que alguém que recebeu senha temporária cria a própria."""
    if request.method == "POST":
        current = request.form.get("current") or ""
        new = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if not current_user.check_password(current):
            flash("A senha atual não confere.", "error")
        elif len(new) < 6:
            flash("A senha nova precisa de pelo menos 6 caracteres.", "error")
        elif new != confirm:
            flash("As senhas novas não conferem.", "error")
        else:
            current_user.set_password(new)
            # Trocar a senha derruba as outras sessões (o celular esquecido
            # logado na casa de alguém, por exemplo); esta continua.
            current_user.end_other_sessions()
            db.session.commit()
            login_user(current_user, remember=True)
            flash("Senha alterada. Outros aparelhos conectados foram desconectados.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("auth/account.html")


@bp.route("/conta/sair-de-todos", methods=["POST"])
@login_required
def logout_everywhere():
    """Desconecta todos os aparelhos, inclusive "continuar conectado"."""
    current_user.end_other_sessions()
    db.session.commit()
    logout_user()
    flash("Você saiu de todos os aparelhos. Entre de novo aqui.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/sair")
@login_required
def logout():
    logout_user()
    flash("Até a próxima sessão.", "success")
    return redirect(url_for("main.index"))
