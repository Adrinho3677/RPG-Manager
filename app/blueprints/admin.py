# -*- coding: utf-8 -*-
"""Administração do site: erros, usuários, arquivos e backup.

Feito para quem hospeda no plano gratuito do PythonAnywhere: tudo que antes
exigia o console (ou um e-mail que o plano não manda) fica numa página.
"""
import secrets
from datetime import datetime
from functools import wraps

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from app import maintenance
from app.extensions import db
from app.models import Campaign, CampaignMember, Character, ErrorReport, User

bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not maintenance.is_admin(current_user):
            abort(404)  # nem conta que a página existe
        return view(*args, **kwargs)
    return wrapper


@bp.app_context_processor
def admin_helpers():
    """Usado no topo de toda página: calcula uma vez por requisição."""
    def is_site_admin():
        if "is_site_admin" not in g:
            g.is_site_admin = maintenance.is_admin(current_user)
        return g.is_site_admin

    def backup_nag():
        if "backup_nag" not in g:
            g.backup_nag = is_site_admin() and maintenance.backup_reminder_due()
        return g.backup_nag
    return {"is_site_admin": is_site_admin, "backup_nag": backup_nag}


def _human(size):
    if size is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return ("%.0f %s" if unit == "B" else "%.1f %s") % (size, unit)
        size /= 1024.0


@bp.route("/")
@admin_required
def index():
    users = User.query.order_by(User.created_at.desc()).all()
    counts = {
        "campaigns": dict(db.session.query(Campaign.master_id, db.func.count(Campaign.id))
                          .group_by(Campaign.master_id).all()),
        "memberships": dict(db.session.query(CampaignMember.user_id, db.func.count(CampaignMember.id))
                            .group_by(CampaignMember.user_id).all()),
        "characters": dict(db.session.query(Character.owner_id, db.func.count(Character.id))
                           .group_by(Character.owner_id).all()),
    }
    usage = maintenance.disk_usage()
    preview = maintenance.cleanup(dry_run=True)
    return render_template(
        "admin/index.html", users=users, counts=counts,
        errors=ErrorReport.query.order_by(ErrorReport.last_at.desc()).limit(50).all(),
        usage={k: _human(v) for k, v in usage.items()}, preview=preview,
        preview_size=_human(preview["bytes"]), days=maintenance.days_since_backup_download(),
        admin_names=maintenance.admin_names(),
    )


@bp.route("/erros/<int:report_id>")
@admin_required
def error_detail(report_id):
    report = db.get_or_404(ErrorReport, report_id)
    return render_template("admin/error.html", report=report)


@bp.route("/erros/limpar", methods=["POST"])
@admin_required
def errors_clear():
    ErrorReport.query.delete()
    db.session.commit()
    flash("Lista de erros limpa.", "success")
    return redirect(url_for("admin.index") + "#erros")


@bp.route("/usuarios/<int:user_id>/senha", methods=["POST"])
@admin_required
def user_password(user_id):
    """Senha temporária para quem esqueceu (substitui o flask redefinir-senha)."""
    user = db.get_or_404(User, user_id)
    temporary = secrets.token_urlsafe(9)
    user.set_password(temporary)
    user.end_other_sessions()
    db.session.commit()
    flash("Senha temporária de %s: %s — passe para a pessoa; ela troca em Minha conta."
          % (user.username, temporary), "success")
    return redirect(url_for("admin.index") + "#usuarios")


@bp.route("/limpar", methods=["POST"])
@admin_required
def cleanup():
    result = maintenance.cleanup()
    flash("Limpeza feita: %d arquivo(s), %s liberados." % (result["files"], _human(result["bytes"])),
          "success")
    return redirect(url_for("admin.index") + "#arquivos")


@bp.route("/backup")
@admin_required
def backup():
    """Baixa o banco (e as imagens) agora: a cópia que fica fora do servidor."""
    try:
        data = maintenance.backup_zip(include_images=request.args.get("imagens") != "0")
    except RuntimeError as error:
        flash(str(error), "error")
        return redirect(url_for("admin.index"))
    maintenance.mark_backup_downloaded()
    name = "grimorio-backup-%s.zip" % datetime.now().strftime("%Y%m%d-%H%M")
    response = send_file(data, mimetype="application/zip", as_attachment=True, download_name=name)
    response.headers["Cache-Control"] = "no-store"
    return response
