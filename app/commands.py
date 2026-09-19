# -*- coding: utf-8 -*-
"""Comandos de administração, rodados pelo terminal:

    flask backup                       copia o banco para instance/backups
    flask redefinir-senha USUARIO      gera uma senha nova para alguém
    flask limpar                       apaga arquivos que sobraram no disco
    flask manutencao                   tudo de uma vez (a tarefa diária)
"""
import os
import secrets
import sqlite3
from datetime import datetime

import click
from sqlalchemy.engine import make_url

from app.extensions import db


def sqlite_path(uri):
    url = make_url(uri)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return url.database


def make_backup(app):
    """Copia o banco SQLite de forma segura mesmo com o site no ar.

    Usa a API de backup do próprio SQLite em vez de copiar o arquivo: uma cópia
    simples feita no meio de uma gravação pode sair corrompida.
    Devolve o caminho do arquivo criado.
    """
    source = sqlite_path(app.config["SQLALCHEMY_DATABASE_URI"])
    if source is None:
        raise click.ClickException(
            "O backup automático só funciona com SQLite. Para MySQL, use o mysqldump "
            "(no PythonAnywhere: aba Databases → instruções de backup)."
        )
    if not os.path.exists(source):
        raise click.ClickException("Banco não encontrado em %s" % source)

    folder = app.config["BACKUP_DIR"]
    os.makedirs(folder, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(folder, "rpgmanager-%s.db" % stamp)
    counter = 2
    while os.path.exists(target):  # dois backups no mesmo segundo não se sobrescrevem
        target = os.path.join(folder, "rpgmanager-%s-%d.db" % (stamp, counter))
        counter += 1

    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    keep = max(1, int(app.config.get("BACKUP_KEEP", 14)))
    copies = [os.path.join(folder, f) for f in os.listdir(folder)
              if f.startswith("rpgmanager-") and f.endswith(".db")]
    copies.sort(key=lambda path: (os.path.getmtime(path), path))
    for path in copies[:-keep]:
        if path != target:
            os.remove(path)

    return target


def register_commands(app):
    @app.cli.command("limpar")
    @click.option("--simular", is_flag=True, help="Só mostra o que seria apagado.")
    def cleanup_command(simular):
        """Apaga retratos sem uso, uploads órfãos e cópias velhas da névoa."""
        from app import maintenance
        result = maintenance.cleanup(dry_run=simular)
        click.echo("%s %d arquivo(s), %.1f MB." % ("Seriam apagados" if simular else "Apagados",
                                                  result["files"], result["bytes"] / 1048576.0))

    @app.cli.command("manutencao")
    def maintenance_command():
        """A tarefa diária: backup, lembretes de sessão e limpeza (o plano gratuito só tem uma)."""
        from app import maintenance, reminders
        try:
            target = make_backup(app)
            click.echo("Backup: %s" % target)
        except click.ClickException as error:
            click.echo("Backup: %s" % error.message)
        click.echo("Lembretes por e-mail enviados: %d" % reminders.send_due())
        result = maintenance.cleanup()
        click.echo("Limpeza: %d arquivo(s), %.1f MB." % (result["files"], result["bytes"] / 1048576.0))
        from datetime import date
        if date.today().weekday() == 0:  # segunda-feira: backup por e-mail, se houver e-mail
            click.echo("Backup por e-mail: %d" % maintenance.email_backup())

    @app.cli.command("backup")
    def backup_command():
        """Faz uma cópia do banco e mantém só as mais recentes."""
        target = make_backup(app)
        size = os.path.getsize(target) / 1024
        click.echo("Backup criado: %s (%.0f KB)" % (target, size))

    @app.cli.command("redefinir-senha")
    @click.argument("usuario")
    @click.option("--senha", default=None, help="Senha nova. Se omitida, uma aleatória é gerada.")
    def reset_password_command(usuario, senha):
        """Define uma senha nova para um usuário (por nome ou e-mail)."""
        from app.models import User

        identifier = usuario.strip().lower()
        user = User.query.filter(
            (db.func.lower(User.username) == identifier) | (User.email == identifier)
        ).first()
        if user is None:
            raise click.ClickException("Usuário não encontrado: %s" % usuario)

        nova = senha or secrets.token_urlsafe(9)
        if len(nova) < 6:
            raise click.ClickException("A senha precisa de pelo menos 6 caracteres.")
        user.set_password(nova)
        user.end_other_sessions()
        db.session.commit()

        click.echo("Senha de %s redefinida." % user.username)
        if not senha:
            click.echo("Senha temporária: %s" % nova)
            click.echo("Peça para a pessoa trocar assim que entrar.")
