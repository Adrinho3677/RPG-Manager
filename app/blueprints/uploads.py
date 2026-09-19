# -*- coding: utf-8 -*-
"""Envio e entrega de imagens: retratos de personagem e mapas da campanha.

Segurança:
- O tipo do arquivo é descoberto pelos primeiros bytes, não pela extensão nem
  pelo que o navegador diz. Só PNG, JPEG, GIF e WEBP. SVG fica de fora de
  propósito: é XML e pode carregar script.
- O nome no disco é um token aleatório, nunca o nome enviado.
- Mapas só são entregues a quem pode ver a campanha (e os marcados "só mestre",
  só ao mestre). Quem não pode recebe 404, para nem confirmar que existe.
- Retratos são entregues a qualquer usuário logado que tenha o link: o token
  tem 128 bits, então não dá para adivinhar, e assim o retrato continua
  aparecendo se a ficha mudar de campanha.
"""
import os
import secrets

from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, send_from_directory, url_for)
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Asset, Campaign

bp = Blueprint("uploads", __name__)


class UploadError(ValueError):
    pass


def sniff_image(head):
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image/gif", "gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None, None


def save_upload(storage, kind, owner, campaign=None, title="", visibility="mesa"):
    """Grava a imagem e cria o Asset (sem commit). Levanta UploadError."""
    if storage is None or not storage.filename:
        raise UploadError("Escolha um arquivo.")

    head = storage.stream.read(16)
    storage.stream.seek(0)
    mimetype, extension = sniff_image(head)
    if mimetype is None:
        raise UploadError("Envie uma imagem PNG, JPG, GIF ou WEBP.")

    token = secrets.token_hex(16)
    filename = "%s.%s" % (token, extension)
    folder = current_app.config["UPLOAD_DIR"]
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, filename)
    storage.save(path)

    asset = Asset(
        token=token,
        owner_id=owner.id,
        campaign_id=campaign.id if campaign else None,
        kind=kind if kind in Asset.KINDS else "mapa",
        title=(title or "").strip()[:160],
        filename=filename,
        mimetype=mimetype,
        size=os.path.getsize(path),
        visibility=visibility if visibility in ("mesa", "mestre") else "mesa",
    )
    db.session.add(asset)
    return asset


def remove_file(asset):
    """Apaga o arquivo do disco. Falhar aqui não pode derrubar a requisição:
    no pior caso sobra um arquivo órfão, e o registro some do mesmo jeito."""
    path = os.path.join(current_app.config["UPLOAD_DIR"], asset.filename)
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as error:
        current_app.logger.warning("Não consegui apagar %s: %s", path, error)


def asset_from_url(url):
    """Asset correspondente a um avatar_url interno, ou None."""
    prefix = Asset.URL_PREFIX
    if not url or not url.startswith(prefix):
        return None
    return Asset.query.filter_by(token=url[len(prefix):].strip("/")).first()


def can_see(asset, user):
    if asset.owner_id == getattr(user, "id", None):
        return True
    if asset.kind == "avatar":
        return True
    campaign = asset.campaign
    if campaign is None:
        return False
    if campaign.is_master(user):
        return True
    if not campaign.can_view(user):
        return False
    if asset.visibility == "mesa":
        return True
    # Mapa escondido na galeria mas posto num mapa tático sem névoa: a mesa
    # precisa vê-lo. Com névoa, o jogador recebe só a cópia recortada
    # (campaigns.board_image), nunca o original.
    return any((e.board or {}).get("map_id") == asset.id and not (e.board or {}).get("fog")
               for e in campaign.encounters)


@bp.route(Asset.URL_PREFIX + "<token>")
@login_required
def serve(token):
    asset = Asset.query.filter_by(token=token).first()
    if asset is None or not can_see(asset, current_user):
        abort(404)
    response = send_from_directory(
        current_app.config["UPLOAD_DIR"], asset.filename, mimetype=asset.mimetype, max_age=3600
    )
    # Mesmo que alguém consiga enviar algo estranho, o navegador não tenta
    # adivinhar o tipo nem executa nada que venha daqui.
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'"
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


# ------------------------------------------------------------ galeria de mapas
def _campaign_or_403(campaign_id):
    campaign = db.session.get(Campaign, campaign_id) or abort(404)
    if not campaign.can_view(current_user):
        abort(403)
    return campaign


@bp.route("/campanhas/<int:campaign_id>/mapas", methods=["GET", "POST"])
@login_required
def gallery(campaign_id):
    campaign = _campaign_or_403(campaign_id)
    is_master = campaign.is_master(current_user)

    if request.method == "POST":
        visibility = request.form.get("visibility", "mesa")
        if not is_master:
            visibility = "mesa"  # só o mestre guarda imagem escondida
        try:
            save_upload(
                request.files.get("file"), "mapa", current_user, campaign,
                title=request.form.get("title") or "", visibility=visibility,
            )
            db.session.commit()
            flash("Imagem enviada.", "success")
        except UploadError as error:
            db.session.rollback()
            flash(str(error), "error")
        return redirect(url_for("uploads.gallery", campaign_id=campaign.id))

    query = campaign.assets.filter(Asset.kind == "mapa")
    if not is_master:
        query = query.filter(Asset.visibility == "mesa")
    return render_template(
        "campaigns/gallery.html",
        campaign=campaign,
        is_master=is_master,
        assets=query.order_by(Asset.created_at.desc()).all(),
    )


@bp.route("/campanhas/<int:campaign_id>/mapas/<int:asset_id>/revelar", methods=["POST"])
@login_required
def gallery_toggle(campaign_id, asset_id):
    campaign = _campaign_or_403(campaign_id)
    if not campaign.is_master(current_user):
        abort(403)
    asset = Asset.query.filter_by(id=asset_id, campaign_id=campaign.id, kind="mapa").first_or_404()
    asset.visibility = "mesa" if asset.visibility == "mestre" else "mestre"
    db.session.commit()
    flash("Imagem %s." % ("revelada para a mesa" if asset.visibility == "mesa" else "escondida"),
          "success")
    return redirect(url_for("uploads.gallery", campaign_id=campaign.id))


@bp.route("/campanhas/<int:campaign_id>/mapas/<int:asset_id>/excluir", methods=["POST"])
@login_required
def gallery_delete(campaign_id, asset_id):
    campaign = _campaign_or_403(campaign_id)
    asset = Asset.query.filter_by(id=asset_id, campaign_id=campaign.id, kind="mapa").first_or_404()
    if asset.owner_id != current_user.id and not campaign.is_master(current_user):
        abort(403)
    remove_file(asset)
    db.session.delete(asset)
    db.session.commit()
    flash("Imagem excluída.", "success")
    return redirect(url_for("uploads.gallery", campaign_id=campaign.id))
