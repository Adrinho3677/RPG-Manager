# -*- coding: utf-8 -*-
"""Imagem do mapa com a névoa "queimada" nela, para os jogadores.

Pintar a névoa por cima no navegador não guarda segredo nenhum: a imagem
inteira já foi baixada. Aqui o servidor gera uma cópia com a névoa "queimada"
— os mesmos traços de pincel que o mestre pintou —, e é só essa cópia que o
jogador recebe.

As cópias ficam em UPLOAD_DIR/nevoa/, com o resumo do que está revelado no
nome: revelar de novo o mesmo conjunto reaproveita o arquivo. Guarda poucas
por mapa e apaga as antigas.
"""
import glob
import math
import os

from flask import current_app

MAX_SIDE_PX = 3000     # mapas gigantes são reduzidos: menos CPU, arquivo menor
KEEP_PER_MAP = 4
FOG_COLOR = (10, 9, 16)


def _cache_dir():
    path = os.path.join(current_app.config["UPLOAD_DIR"], "nevoa")
    os.makedirs(path, exist_ok=True)
    return path


def masked_path(asset, board, key):
    """Caminho da imagem recortada (gera se ainda não existe)."""
    folder = _cache_dir()
    target = os.path.join(folder, "mapa%d-%s.jpg" % (asset.id, key))
    if os.path.exists(target):
        return target

    from PIL import Image, ImageDraw

    source = os.path.join(current_app.config["UPLOAD_DIR"], asset.filename)
    with Image.open(source) as original:
        original.seek(0)  # GIF animado: só o primeiro quadro
        image = original.convert("RGB")
    image.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    width, height = image.size
    cell_w, cell_h = width / float(board["cols"]), height / float(board["rows"])

    # Máscara: 255 = coberto pela névoa, 0 = revelado. Mesma conta do navegador.
    layer = board["fog_layer"]
    mask = Image.new("L", image.size, 255 if layer["base"] == "cover" else 0)
    draw = ImageDraw.Draw(mask)
    for cell in board["revealed"]:          # névoa antiga, por quadrado
        try:
            x, y = (int(part) for part in cell.split(","))
        except ValueError:
            continue
        draw.rectangle([math.floor(x * cell_w), math.floor(y * cell_h),
                        math.ceil((x + 1) * cell_w), math.ceil((y + 1) * cell_h)], fill=0)
    for stroke in layer["strokes"]:         # pincel: traços com ponta redonda
        tone = 0 if stroke["mode"] == "reveal" else 255
        radius = max(1.0, stroke["size"] * (cell_w + cell_h) / 2.0)
        points = [(px * cell_w, py * cell_h) for px, py in stroke["points"]]
        if len(points) > 1:
            draw.line(points, fill=tone, width=int(round(radius * 2)), joint="curve")
        for px, py in points:
            draw.ellipse([px - radius, py - radius, px + radius, py + radius], fill=tone)

    image = Image.composite(Image.new("RGB", image.size, FOG_COLOR), image, mask)

    temp = target + ".tmp"
    image.save(temp, "JPEG", quality=85)
    os.replace(temp, target)  # quem pedir junto nunca lê um arquivo pela metade
    _prune(folder, asset.id)
    return target


def _prune(folder, asset_id):
    files = sorted(glob.glob(os.path.join(folder, "mapa%d-*.jpg" % asset_id)),
                   key=os.path.getmtime, reverse=True)
    for old in files[KEEP_PER_MAP:]:
        try:
            os.remove(old)
        except OSError:
            pass
