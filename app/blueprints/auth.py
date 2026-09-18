# -*- coding: utf-8 -*-
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.models import User

bp = Blueprint("auth", __name__)


@bp.route("/entrar", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        identifier = (request.form.get("identifier") or "").strip().lower()
        password = request.form.get("password") or ""
        user = User.query.filter(
            (User.email == identifier) | (User.username == identifier)
        ).first()
        if user and user.check_password(password):
            login_user(user, remember=bool(request.form.get("remember")))
            destination = request.args.get("next")
            if not destination or not destination.startswith("/"):
                destination = url_for("main.dashboard")
            return redirect(destination)
        flash("Usuário ou senha inválidos.", "error")

    return render_template("auth/login.html")


@bp.route("/cadastro", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""

        errors = []
        if len(username) < 3:
            errors.append("O nome de usuário precisa de pelo menos 3 caracteres.")
        if "@" not in email:
            errors.append("Informe um e-mail válido.")
        if len(password) < 6:
            errors.append("A senha precisa de pelo menos 6 caracteres.")
        if password != confirm:
            errors.append("As senhas não conferem.")
        if User.query.filter_by(username=username).first():
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
        return redirect(url_for("main.dashboard"))

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
