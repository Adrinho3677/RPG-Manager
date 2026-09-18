# -*- coding: utf-8 -*-
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from app import security
from app.extensions import db
from app.models import User

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
        if "@" not in email:
            errors.append("Informe um e-mail válido.")
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
            db.session.commit()
            flash("Senha alterada.", "success")
            return redirect(url_for("main.dashboard"))
    return render_template("auth/account.html")


@bp.route("/sair")
@login_required
def logout():
    logout_user()
    flash("Até a próxima sessão.", "success")
    return redirect(url_for("main.index"))
