# -*- coding: utf-8 -*-
"""Manutenção do site: erros, limpeza de arquivos e backup para baixar.

Tudo pensado para o plano gratuito do PythonAnywhere, que não manda e-mail nem
tem tarefa agendada: o administrador vê os erros numa página, baixa o backup
por um botão, e a manutenção diária (backup + lembretes + limpeza) roda sozinha
no primeiro acesso de cada dia — ou à mão, com `flask manutencao` no Bash.
Se um dia houver e-mail configurado, os avisos também vão por lá.
"""
import hashlib
import io
import os
import tempfile
import traceback
import zipfile
from datetime import datetime, timedelta

from flask import current_app, request

from app.extensions import db
from app.models import Asset, Character, Encounter, ErrorReport, SiteSetting, User

ORPHAN_MIN_AGE = timedelta(days=1)   # arquivo recém-enviado ainda pode estar sendo usado
BACKUP_REMINDER_DAYS = 7
MAX_REPORTS = 200


# ------------------------------------------------------------------ admin
def admin_names():
    raw = current_app.config.get("ADMIN_USERNAMES") or ""
    return {n.strip().lower() for n in raw.split(",") if n.strip()}


def is_admin(user):
    """Administrador do site: quem está em ADMIN_USERNAMES; sem a variável, a
    primeira conta criada (em geral, quem instalou o site)."""
    if not getattr(user, "is_authenticated", False):
        return False
    names = admin_names()
    if names:
        return user.username.lower() in names
    first = db.session.query(db.func.min(User.id)).scalar()
    return user.id == first


def admins():
    names = admin_names()
    if names:
        return [u for u in User.query.all() if u.username.lower() in names]
    first = User.query.order_by(User.id).first()
    return [first] if first else []


# ------------------------------------------------------------------ erros
def record_error(error):
    """Guarda um erro 500 (agrupando repetições) e avisa por e-mail se der."""
    try:
        db.session.rollback()
        trace = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        frames = traceback.extract_tb(error.__traceback__)
        where = "%s:%s" % (frames[-1].filename, frames[-1].lineno) if frames else ""
        signature = hashlib.sha1(("%s|%s" % (type(error).__name__, where)).encode()).hexdigest()
        report = ErrorReport.query.filter_by(signature=signature).first()
        summary = ("%s: %s" % (type(error).__name__, error))[:300]
        first_time = report is None
        if report is None:
            report = ErrorReport(signature=signature, count=0, first_at=datetime.utcnow())
            db.session.add(report)
        report.count = (report.count or 0) + 1
        report.last_at = datetime.utcnow()
        report.summary = summary
        report.traceback = trace[-20000:]
        report.path = (request.path if request else "")[:300]
        report.method = (request.method if request else "")[:10]
        from flask_login import current_user
        report.user_id = current_user.id if getattr(current_user, "is_authenticated", False) else None
        # Só os mais recentes: o banco não cresce para sempre.
        old = ErrorReport.query.order_by(ErrorReport.last_at.desc()).offset(MAX_REPORTS).all()
        for item in old:
            db.session.delete(item)
        db.session.commit()
        if first_time:
            _email_admins("Grimório: erro novo em %s" % report.path,
                          "Um erro novo aconteceu no site.\n\n%s %s\n%s\n\n%s"
                          % (report.method, report.path, summary, trace[-4000:]))
    except Exception:  # registrar o erro nunca pode causar outro erro
        db.session.rollback()
        current_app.logger.exception("Não consegui registrar o erro")


def _email_admins(subject, body, attachments=None):
    from app import mail
    if not mail.enabled():
        return 0
    return sum(1 for user in admins() if mail.send(user.email, subject, body, attachments))


# ---------------------------------------------------------------- limpeza
def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _old_enough(path, now):
    try:
        return now - datetime.fromtimestamp(os.path.getmtime(path)) >= ORPHAN_MIN_AGE
    except OSError:
        return False


def cleanup(dry_run=False):
    """Apaga o que sobrou no disco. Devolve {"files": n, "bytes": n, "rows": n}.

    - arquivos em uploads/ sem registro no banco (upload interrompido etc.);
    - retratos que nenhuma ficha usa mais (trocados ou de fichas excluídas);
    - cópias da névoa de mapas que não existem mais.
    Nada com menos de um dia é tocado: pode estar em uso agora mesmo.
    """
    folder = current_app.config["UPLOAD_DIR"]
    now = datetime.now()
    result = {"files": 0, "bytes": 0, "rows": 0}
    if not os.path.isdir(folder):
        return result

    def remove(path):
        result["files"] += 1
        result["bytes"] += _size(path)
        if not dry_run:
            try:
                os.remove(path)
            except OSError:
                result["files"] -= 1

    used_avatars = {url for (url,) in db.session.query(Character.avatar_url).filter(
        Character.avatar_url.like(Asset.URL_PREFIX + "%"))}
    for asset in Asset.query.filter_by(kind="avatar").all():
        if asset.url in used_avatars or not asset.created_at:
            continue
        if datetime.utcnow() - asset.created_at < ORPHAN_MIN_AGE:
            continue
        remove(os.path.join(folder, asset.filename))
        result["rows"] += 1
        if not dry_run:
            db.session.delete(asset)

    known = {a.filename for a in Asset.query.all()}
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and name not in known and _old_enough(path, now):
            remove(path)

    fog = os.path.join(folder, "nevoa")
    if os.path.isdir(fog):
        live_maps = {e.board.get("map_id") for e in Encounter.query.all()
                     if isinstance(e.board, dict) and e.board.get("fog")}
        for name in os.listdir(fog):
            try:
                map_id = int(name.split("-", 1)[0].replace("mapa", ""))
            except ValueError:
                map_id = None
            path = os.path.join(fog, name)
            if map_id not in live_maps and _old_enough(path, now):
                remove(path)
    if not dry_run:
        db.session.commit()
    return result


def disk_usage():
    """Quanto cada parte ocupa, em bytes."""
    from app.commands import sqlite_path

    def folder_size(path):
        total = 0
        for root, _, files in os.walk(path):
            total += sum(_size(os.path.join(root, f)) for f in files)
        return total

    database = sqlite_path(current_app.config["SQLALCHEMY_DATABASE_URI"])
    return {
        "database": _size(database) if database else None,
        "uploads": folder_size(current_app.config["UPLOAD_DIR"]),
        "backups": folder_size(current_app.config["BACKUP_DIR"]),
    }


# ----------------------------------------------------------------- backup
def backup_zip(include_images=True):
    """ZIP com uma cópia consistente do banco (e as imagens), num arquivo temporário."""
    import sqlite3
    from app.commands import sqlite_path
    source = sqlite_path(current_app.config["SQLALCHEMY_DATABASE_URI"])
    if source is None or not os.path.exists(source):
        raise RuntimeError("O backup por aqui só funciona com SQLite (no MySQL, use a aba Databases).")
    handle, snapshot = tempfile.mkstemp(suffix=".db")
    os.close(handle)
    try:
        src, dst = sqlite3.connect(source), sqlite3.connect(snapshot)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        buffer = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, "rpgmanager.db")
            if include_images:
                folder = current_app.config["UPLOAD_DIR"]
                for name in (os.listdir(folder) if os.path.isdir(folder) else []):
                    path = os.path.join(folder, name)
                    if os.path.isfile(path):
                        archive.write(path, "uploads/" + name)
            archive.writestr("LEIA-ME.txt", BACKUP_README)
        buffer.seek(0)
        return buffer
    finally:
        try:
            os.remove(snapshot)
        except OSError:
            pass


BACKUP_README = """Backup do Grimório

rpgmanager.db   o banco inteiro (SQLite)
uploads/        imagens enviadas (retratos e mapas)

Para restaurar no PythonAnywhere: pare o site (Web > Disable), troque
instance/rpgmanager.db por este arquivo e a pasta instance/uploads pelo
conteúdo de uploads/, e reative o site.
"""


def mark_backup_downloaded():
    SiteSetting.put("backup_baixado_em", datetime.utcnow().isoformat())
    db.session.commit()


def days_since_backup_download():
    raw = SiteSetting.get("backup_baixado_em")
    if not raw:
        return None
    try:
        return (datetime.utcnow() - datetime.fromisoformat(raw)).days
    except ValueError:
        return None


def backup_reminder_due():
    days = days_since_backup_download()
    return days is None or days >= BACKUP_REMINDER_DAYS


def email_backup(max_bytes=8 * 1024 * 1024):
    """Manda o backup (só o banco) por e-mail aos administradores, se couber e se houver e-mail."""
    from app import mail
    if not mail.enabled():
        return 0
    data = backup_zip(include_images=False).read()
    if len(data) > max_bytes:
        current_app.logger.warning("Backup grande demais para e-mail (%d bytes).", len(data))
        return 0
    name = "grimorio-%s.zip" % datetime.now().strftime("%Y%m%d")
    return _email_admins("Grimório: backup de %s" % datetime.now().strftime("%d/%m/%Y"),
                         "Segue o backup do banco do Grimório (sem as imagens).",
                         [(name, "application/zip", data)])


# ------------------------------------------------- manutenção diária
DAILY = timedelta(hours=24)
LAST_RUN_KEY = "manutencao_em"


def run_all(app):
    """Backup + lembretes + limpeza (+ backup por e-mail às segundas). Devolve as linhas do relatório."""
    import click
    from app import reminders
    from app.commands import make_backup
    lines = []
    try:
        lines.append("Backup: %s" % os.path.basename(make_backup(app)))
    except click.ClickException as error:
        lines.append("Backup: %s" % error.message)
    lines.append("Lembretes por e-mail enviados: %d" % reminders.send_due())
    result = cleanup()
    lines.append("Limpeza: %d arquivo(s), %.1f MB." % (result["files"], result["bytes"] / 1048576.0))
    if datetime.now().weekday() == 0:
        lines.append("Backup por e-mail: %d" % email_backup())
    SiteSetting.put("manutencao_relatorio", " · ".join(lines))
    db.session.commit()
    return lines


def last_run():
    raw = SiteSetting.get(LAST_RUN_KEY)
    try:
        return datetime.fromisoformat(raw) if raw else None
    except ValueError:
        return None


def claim_daily_run(now=None):
    """Marca "rodando agora" se já passou um dia. True só para quem conseguiu marcar.

    Duas requisições ao mesmo tempo não rodam a manutenção duas vezes: a marca
    só é gravada se ainda for a que foi lida (compare-and-swap no banco).
    """
    from sqlalchemy import text
    now = now or datetime.utcnow()
    previous = SiteSetting.get(LAST_RUN_KEY)
    if previous:
        try:
            if now - datetime.fromisoformat(previous) < DAILY:
                return False
        except ValueError:
            pass
        result = db.session.execute(
            text("UPDATE site_settings SET value = :new WHERE key = :key AND value = :old"),
            {"new": now.isoformat(), "key": LAST_RUN_KEY, "old": previous})
        won = result.rowcount == 1
    else:
        try:
            db.session.add(SiteSetting(key=LAST_RUN_KEY, value=now.isoformat()))
            db.session.flush()
            won = True
        except Exception:
            db.session.rollback()
            return False
    db.session.commit()
    return won


def register_daily(app):
    """No plano gratuito não há tarefa agendada: o primeiro acesso de cada dia
    dispara a manutenção, depois que a resposta já saiu (ninguém espera por ela)."""

    @app.after_request
    def daily_maintenance(response):
        if not app.config.get("AUTO_MAINTENANCE") or request.path.startswith("/static/"):
            return response
        try:
            due = claim_daily_run()
        except Exception:
            db.session.rollback()
            return response
        if due:
            def run():
                with app.app_context(), app.test_request_context(base_url=app.config.get("SITE_URL") or None):
                    try:
                        run_all(app)
                    except Exception:
                        db.session.rollback()
                        app.logger.exception("Falha na manutenção diária")
            response.call_on_close(run)
        return response
