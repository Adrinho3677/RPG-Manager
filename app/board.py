# -*- coding: utf-8 -*-
"""Mapa tático de um combate: grade, imagem de fundo, fichas e névoa.

O estado fica em Encounter.board (JSON):

    map_id        Asset (kind "mapa") da campanha usado de fundo, ou None
    cols, rows    tamanho da grade em quadrados (aceita quebrado: 18,5 × 14,35 —
                  a última coluna/linha fica parcial, como no mapa de verdade)
    grid          mostrar as linhas da grade
    cell_size     quanto vale um quadrado (1.5) ...
    cell_unit     ... e em que unidade ("m")
    fog           névoa de guerra ligada
    revealed      quadrados revelados (névoa antiga, por quadrado) — "x,y"
    fog_layer     névoa pintada à mão: {"base": "cover"|"reveal", "strokes": [...]},
                  cada traço {"mode": "reveal"|"cover", "size": raio em quadrados,
                  "points": [[x, y], ...]} — salas redondas sem virar escadinha
    players_move  jogadores podem mover as próprias fichas
    tokens        {uid do combatente: {"x", "y", "hidden"}}
    areas         áreas de efeito [{id, shape (circle|cone|line), ox, oy, angle, size,
                  owner, who}] — origem e tamanho em quadrados
    markers       {id: {type, x, y, label, hidden}} — portas, armadilhas etc.
    history       últimos movimentos [{uid, fx, fy, by}] — para desfazer
    version       sobe a cada mudança

As fichas do mapa SÃO os combatentes do rastreador (mesmo uid): nada de
cadastro duplicado. Combatente fora de `tokens` está "fora do mapa".

Segredos, como no rastreador: para jogadores, fichas escondidas pelo mestre e
inimigos debaixo da névoa nem entram na resposta.
"""
import hashlib
import secrets

from flask import url_for

from app.utils import to_float, to_int

MAX_SIDE = 60
MIN_SIDE = 0.5
DEFAULTS = {
    "map_id": None,
    "cols": 20.0,
    "rows": 14.0,
    "grid": True,
    "cell_size": 1.5,
    "cell_unit": "m",
    "fog": False,
    "revealed": [],
    "fog_layer": {"base": "cover", "strokes": []},
    "players_move": True,
    "tokens": {},
    "areas": [],
    "markers": {},
    "history": [],
    "version": 0,
}
MAX_TOKEN_SIZE = 4   # criaturas grandes ocupam 2×2, 3×3 ou 4×4 quadrados
MAX_STROKES = 500          # traços de névoa guardados
MAX_STROKE_POINTS = 400    # pontos de um traço
MAX_TOTAL_POINTS = 12000   # soma de todos: o JSON do mapa não pode crescer sem fim
MAX_BRUSH = 12             # raio do pincel, em quadrados
MAX_HISTORY = 30
MAX_AREAS = 30
MAX_MARKERS = 80
AREA_SHAPES = ("circle", "cone", "line")
MARKER_TYPES = {
    "porta": "🚪", "armadilha": "⚠️", "tesouro": "💰", "alvo": "🎯", "nota": "📌",
}


class BoardError(ValueError):
    """Pedido inválido: vira 400 com a mensagem para a pessoa."""


def _clamp(value, low, high):
    return max(low, min(high, value))


def _cell(x, y):
    return "%d,%d" % (x, y)


def cells_across(value):
    """Quantos quadrados existem numa medida quebrada (18,5 → 19: o último é parcial)."""
    import math
    return max(1, int(math.ceil(float(value) - 1e-9)))


def _side(value, fallback):
    """Lado da grade: número quebrado vale (18,5); lixo ou zero volta ao padrão."""
    size = to_float(value, 0)
    if not MIN_SIDE <= size <= MAX_SIDE:
        size = fallback
    return round(size, 3)


def normalize(raw):
    """Sempre devolve um tabuleiro completo e dentro dos limites."""
    raw = raw if isinstance(raw, dict) else {}
    board = dict(DEFAULTS)
    board["map_id"] = to_int(raw.get("map_id"), 0) or None
    board["cols"] = _side(raw.get("cols"), DEFAULTS["cols"])
    board["rows"] = _side(raw.get("rows"), DEFAULTS["rows"])
    wide, high = cells_across(board["cols"]), cells_across(board["rows"])
    board["grid"] = bool(raw.get("grid", True))
    size = to_float(raw.get("cell_size"), DEFAULTS["cell_size"])
    board["cell_size"] = size if 0 < size <= 1000 else DEFAULTS["cell_size"]
    board["cell_unit"] = str(raw.get("cell_unit") if raw.get("cell_unit") is not None
                             else DEFAULTS["cell_unit"]).strip()[:8]
    board["fog"] = bool(raw.get("fog"))
    board["players_move"] = bool(raw.get("players_move", True))
    board["version"] = max(0, to_int(raw.get("version"), 0))

    revealed = set()
    for item in raw.get("revealed") or []:
        try:
            x, y = (int(part) for part in str(item).split(","))
        except ValueError:
            continue
        if 0 <= x < wide and 0 <= y < high:
            revealed.add(_cell(x, y))
    board["revealed"] = sorted(revealed)
    board["fog_layer"] = _clean_layer(raw.get("fog_layer"))

    tokens = {}
    for uid, pos in (raw.get("tokens") or {}).items():
        if not isinstance(pos, dict):
            continue
        size = _clamp(to_int(pos.get("size"), 1), 1, MAX_TOKEN_SIZE)
        tokens[str(uid)[:16]] = {
            "x": _clamp(to_int(pos.get("x"), 0), 0, max(0, wide - size)),
            "y": _clamp(to_int(pos.get("y"), 0), 0, max(0, high - size)),
            "hidden": bool(pos.get("hidden")),
            "size": size,
        }
    board["tokens"] = tokens
    history = []
    for entry in raw.get("history") or []:
        if isinstance(entry, dict) and entry.get("uid"):
            history.append({"uid": str(entry["uid"])[:16],
                            "fx": None if entry.get("fx") is None else to_int(entry.get("fx"), 0),
                            "fy": None if entry.get("fy") is None else to_int(entry.get("fy"), 0),
                            "by": to_int(entry.get("by"), 0)})
    board["history"] = history[-MAX_HISTORY:]

    areas = []
    for area in raw.get("areas") or []:
        if not isinstance(area, dict) or area.get("shape") not in AREA_SHAPES:
            continue
        areas.append({
            "id": str(area.get("id") or "")[:16] or secrets.token_hex(4),
            "shape": area["shape"],
            "ox": _clamp(to_float(area.get("ox"), 0), 0, board["cols"]),
            "oy": _clamp(to_float(area.get("oy"), 0), 0, board["rows"]),
            "angle": to_float(area.get("angle"), 0) % 360,
            "size": _clamp(to_float(area.get("size"), 1), 0.5, MAX_SIDE * 2),
            "owner": to_int(area.get("owner"), 0),
            "who": str(area.get("who") or "")[:64],
        })
    board["areas"] = areas[-MAX_AREAS:]

    markers = {}
    for mid, marker in (raw.get("markers") or {}).items():
        if not isinstance(marker, dict) or marker.get("type") not in MARKER_TYPES:
            continue
        markers[str(mid)[:16]] = {
            "type": marker["type"],
            "x": _clamp(to_int(marker.get("x"), 0), 0, wide - 1),
            "y": _clamp(to_int(marker.get("y"), 0), 0, high - 1),
            "label": str(marker.get("label") or "").strip()[:60],
            "hidden": bool(marker.get("hidden", True)),
        }
    board["markers"] = markers
    return board


# --------------------------------------------------------------- alterações
def configure(board, payload, map_ids):
    """Mestre: imagem, tamanho da grade, escala e regras."""
    if "map_id" in payload:
        map_id = to_int(payload.get("map_id"), 0) or None
        if map_id is not None and map_id not in map_ids:
            raise BoardError("Esse mapa não é desta campanha.")
        board["map_id"] = map_id
    for key in ("cols", "rows"):
        if key in payload:
            size = to_float(payload.get(key), 0)
            if not MIN_SIDE <= size <= MAX_SIDE:
                raise BoardError("A grade vai de %s a %d quadrados (pode ser quebrado: 18,5)."
                                 % (str(MIN_SIDE).replace(".", ","), MAX_SIDE))
            board[key] = round(size, 3)
    if "cell_size" in payload:
        size = to_float(payload.get("cell_size"), 0)
        if not 0 < size <= 1000:
            raise BoardError("O tamanho do quadrado precisa ser maior que zero.")
        board["cell_size"] = size
    if "cell_unit" in payload:
        board["cell_unit"] = str(payload.get("cell_unit") or "").strip()[:8]
    for key in ("grid", "fog", "players_move"):
        if key in payload:
            board[key] = bool(payload.get(key))
    # Grade menor: fichas que ficaram de fora vão para a borda e a névoa
    # revelada fora da grade é descartada.
    return normalize(board)


def footprint(pos):
    """Quadrados ocupados por uma ficha (criatura grande ocupa vários)."""
    size = pos.get("size", 1)
    return [(pos["x"] + dx, pos["y"] + dy) for dx in range(size) for dy in range(size)]


def move(board, uid, x, y, by=0):
    """x/y None tira a ficha do mapa. Guarda de onde veio, para desfazer."""
    current = board["tokens"].get(uid)
    before = (current["x"], current["y"]) if current else (None, None)
    if x is None or y is None:
        board["tokens"].pop(uid, None)
    else:
        x, y = to_int(x, -1), to_int(y, -1)
        size = (current or {}).get("size", 1)
        # O último quadrado de uma grade quebrada (18,5) é parcial, mas existe.
        if not (0 <= x <= cells_across(board["cols"]) - size
                and 0 <= y <= cells_across(board["rows"]) - size):
            raise BoardError("Fora do mapa.")
        board["tokens"][uid] = {"x": x, "y": y, "hidden": bool((current or {}).get("hidden")),
                                "size": size}
    if before != (x, y):
        board["history"].append({"uid": uid, "fx": before[0], "fy": before[1], "by": by})
        del board["history"][:-MAX_HISTORY]
    return board


def undo(board, user_id, is_master, allowed):
    """Desfaz o último movimento desta pessoa (o mestre desfaz o último de qualquer um).

    `allowed(uid)` diz se a pessoa ainda pode mexer naquela ficha.
    """
    for index in range(len(board["history"]) - 1, -1, -1):
        entry = board["history"][index]
        if not is_master and entry["by"] != user_id:
            continue
        if not allowed(entry["uid"]):
            continue
        del board["history"][index]
        current = board["tokens"].get(entry["uid"])
        if entry["fx"] is None:
            board["tokens"].pop(entry["uid"], None)
        else:
            size = (current or {}).get("size", 1)
            board["tokens"][entry["uid"]] = {
                "x": _clamp(entry["fx"], 0, max(0, cells_across(board["cols"]) - size)),
                "y": _clamp(entry["fy"], 0, max(0, cells_across(board["rows"]) - size)),
                "hidden": bool((current or {}).get("hidden")), "size": size}
        return board
    raise BoardError("Nada para desfazer.")


def set_hidden(board, uid, hidden):
    if uid not in board["tokens"]:
        raise BoardError("Essa ficha não está no mapa.")
    board["tokens"][uid]["hidden"] = bool(hidden)
    return board


def set_size(board, uid, size):
    token = board["tokens"].get(uid)
    if token is None:
        raise BoardError("Essa ficha não está no mapa.")
    size = _clamp(to_int(size, 1), 1, MAX_TOKEN_SIZE)
    token["size"] = size
    token["x"] = _clamp(token["x"], 0, max(0, cells_across(board["cols"]) - size))
    token["y"] = _clamp(token["y"], 0, max(0, cells_across(board["rows"]) - size))
    return board


def parse_speed(text, cell_size):
    """ "9 m", "9m", "18 metros", "30" → quadrados (9 m ÷ 1,5 m = 6). None se não houver número."""
    import re
    match = re.search(r"(\d+(?:[.,]\d+)?)", str(text or ""))
    if not match or not cell_size:
        return None
    value = float(match.group(1).replace(",", "."))
    return round(value / cell_size, 2) if value > 0 else None


def _clean_layer(raw):
    """Camada de névoa válida (traços dentro dos limites)."""
    raw = raw if isinstance(raw, dict) else {}
    strokes, total = [], 0
    for item in (raw.get("strokes") or [])[-MAX_STROKES:]:
        if not isinstance(item, dict) or item.get("mode") not in ("reveal", "cover"):
            continue
        points = []
        for point in (item.get("points") or [])[:MAX_STROKE_POINTS]:
            try:
                points.append([round(float(point[0]), 3), round(float(point[1]), 3)])
            except (TypeError, ValueError, IndexError):
                continue
        if not points or total + len(points) > MAX_TOTAL_POINTS:
            continue
        total += len(points)
        size = to_float(item.get("size"), 1)
        strokes.append({"mode": item["mode"], "size": min(MAX_BRUSH, max(0.05, size)),
                        "points": points})
    base = "reveal" if raw.get("base") == "reveal" else "cover"
    return {"base": base, "strokes": strokes}


def paint_fog(board, payload):
    """Guarda um traço de pincel (ou uma lista de quadrados, da névoa antiga)."""
    layer = board["fog_layer"]
    mode = "reveal" if payload.get("reveal") else "cover"

    points = []
    for point in (payload.get("points") or [])[:MAX_STROKE_POINTS]:
        try:
            points.append([round(float(point[0]), 3), round(float(point[1]), 3)])
        except (TypeError, ValueError, IndexError):
            continue
    if points:
        if sum(len(s["points"]) for s in layer["strokes"]) + len(points) > MAX_TOTAL_POINTS:
            raise BoardError("A névoa deste mapa já tem pintura demais. Use “Cobrir tudo” "
                             "(ou “Revelar tudo”) e pinte de novo.")
        size = min(MAX_BRUSH, max(0.05, to_float(payload.get("size"), 1)))
        layer["strokes"].append({"mode": mode, "size": size, "points": points})
        del layer["strokes"][:-MAX_STROKES]
        return board

    # Névoa antiga (quadrados inteiros) — ainda usada por quem pinta com o teclado.
    revealed = set(board["revealed"])
    wide, high = cells_across(board["cols"]), cells_across(board["rows"])
    for item in (payload.get("cells") or [])[:MAX_SIDE * MAX_SIDE]:
        try:
            x, y = int(item[0]), int(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= x < wide and 0 <= y < high:
            (revealed.add if mode == "reveal" else revealed.discard)(_cell(x, y))
    board["revealed"] = sorted(revealed)
    return board


def fog_all(board, reveal):
    """Revela ou cobre o mapa inteiro: limpa a pintura e começa de novo."""
    board["revealed"] = []
    board["fog_layer"] = {"base": "reveal" if reveal else "cover", "strokes": []}
    return board


def _near_stroke(stroke, x, y):
    """O ponto está dentro do traço (distância até a linha ≤ raio do pincel)?"""
    radius = stroke["size"]
    points = stroke["points"]
    for index, (px, py) in enumerate(points):
        dx, dy = x - px, y - py
        if dx * dx + dy * dy <= radius * radius:
            return True
        if index + 1 < len(points):
            qx, qy = points[index + 1]
            vx, vy = qx - px, qy - py
            length = vx * vx + vy * vy
            if length:
                t = max(0.0, min(1.0, (dx * vx + dy * vy) / length))
                ox, oy = x - (px + t * vx), y - (py + t * vy)
                if ox * ox + oy * oy <= radius * radius:
                    return True
    return False


def is_revealed(board, x, y):
    """Aquele ponto (em quadrados) está revelado? Último traço por cima manda."""
    for stroke in reversed(board["fog_layer"]["strokes"]):
        if _near_stroke(stroke, x, y):
            return stroke["mode"] == "reveal"
    if _cell(int(x), int(y)) in board["revealed"]:
        return True
    return board["fog_layer"]["base"] == "reveal"


def add_area(board, payload, user):
    """Área de efeito (círculo, cone ou linha). Qualquer um da mesa pode pôr."""
    shape = payload.get("shape")
    if shape not in AREA_SHAPES:
        raise BoardError("Forma desconhecida.")
    if len(board["areas"]) >= MAX_AREAS:
        raise BoardError("Mapa com áreas demais: limpe algumas.")
    size = to_float(payload.get("size"), 0)
    if not 0 < size <= MAX_SIDE * 2:
        raise BoardError("Tamanho da área inválido.")
    board["areas"].append({
        "id": secrets.token_hex(4), "shape": shape,
        "ox": _clamp(to_float(payload.get("ox"), 0), 0, board["cols"]),
        "oy": _clamp(to_float(payload.get("oy"), 0), 0, board["rows"]),
        "angle": to_float(payload.get("angle"), 0) % 360,
        "size": size, "owner": user.id, "who": user.username,
    })
    return board


def remove_area(board, area_id, user, is_master):
    area = next((a for a in board["areas"] if a["id"] == area_id), None)
    if area is None:
        raise BoardError("Essa área já saiu do mapa.")
    if not is_master and area["owner"] != user.id:
        raise BoardError("Só quem pôs a área (ou o mestre) pode tirá-la.")
    board["areas"].remove(area)
    return board


def clear_areas(board):
    board["areas"] = []
    return board


def change_marker(board, payload):
    """Mestre: põe, move, revela/esconde, renomeia ou tira um marcador."""
    op = payload.get("op")
    if op == "add":
        if payload.get("type") not in MARKER_TYPES:
            raise BoardError("Tipo de marcador desconhecido.")
        if len(board["markers"]) >= MAX_MARKERS:
            raise BoardError("Marcadores demais neste mapa.")
        x, y = to_int(payload.get("x"), -1), to_int(payload.get("y"), -1)
        if not (0 <= x < cells_across(board["cols"]) and 0 <= y < cells_across(board["rows"])):
            raise BoardError("Fora do mapa.")
        board["markers"][secrets.token_hex(4)] = {
            "type": payload["type"], "x": x, "y": y, "hidden": True,
            "label": str(payload.get("label") or "").strip()[:60]}
        return board
    marker = board["markers"].get(str(payload.get("id")))
    if marker is None:
        raise BoardError("Esse marcador não está mais no mapa.")
    if op == "remove":
        del board["markers"][str(payload.get("id"))]
    elif op == "update":
        if "x" in payload or "y" in payload:
            x, y = to_int(payload.get("x"), marker["x"]), to_int(payload.get("y"), marker["y"])
            if not (0 <= x < cells_across(board["cols"]) and 0 <= y < cells_across(board["rows"])):
                raise BoardError("Fora do mapa.")
            marker.update(x=x, y=y)
        if "hidden" in payload:
            marker["hidden"] = bool(payload.get("hidden"))
        if "label" in payload:
            marker["label"] = str(payload.get("label") or "").strip()[:60]
        if payload.get("type") in MARKER_TYPES:
            marker["type"] = payload["type"]
    else:
        raise BoardError("Operação desconhecida.")
    return board


def fog_key(board):
    """Resumo do que está revelado: muda a URL da imagem recortada."""
    import json
    raw = "%s|%s|%s|%s|%s" % (board["map_id"], board["cols"], board["rows"],
                              ";".join(board["revealed"]),
                              json.dumps(board["fog_layer"], sort_keys=True))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def update(encounter, change):
    """Aplica `change(board)` sem perder o movimento de outra pessoa (ver app/cas.py)."""
    from app.cas import ConflictError, update_json

    def bump(board):
        board = change(board)
        board["version"] += 1
        return board

    try:
        return update_json("encounters", "board", encounter.id, bump, normalize, obj=encounter)
    except ConflictError as error:
        raise BoardError(str(error))


# ------------------------------------------------------------------- leitura
def _avatar(url):
    """Só imagens enviadas ao site ou https: nada de javascript:, data: etc."""
    url = (url or "").strip()
    if url.startswith("/arquivos/") or url.startswith("https://"):
        return url
    return ""


def view(encounter, state, user, is_master, maps):
    """O que o navegador de `user` recebe.

    `state` é o encounter_state() já filtrado para essa pessoa (PV de inimigo
    some para jogador); `maps` é {id: Asset} dos mapas da campanha.
    """
    from app.models import Character

    board = normalize(encounter.board)
    combatants = state["combatants"]
    ids = set()
    for c in combatants:
        ids.update(i for i in (c.get("character_id"), c.get("source_id")) if i)
    sheets = {}
    if ids:
        sheets = {ch.id: ch for ch in Character.query.filter(
            Character.id.in_(ids), Character.campaign_id == encounter.campaign_id)}

    tokens, bench = [], []

    def lit(pos, size=1):
        """Alguma parte da ficha está na luz?"""
        return any(is_revealed(board, cx + 0.5, cy + 0.5)
                   for cx, cy in footprint({"x": pos["x"], "y": pos["y"], "size": size}))
    for index, c in enumerate(combatants):
        uid = c.get("uid")
        if not uid:
            continue
        sheet = sheets.get(c.get("character_id"))
        mine = bool(sheet and user is not None and sheet.owner_id == user.id)
        pos = board["tokens"].get(uid)
        hidden = bool(pos and pos["hidden"])
        if not is_master:
            if hidden and not mine:
                continue
            if (pos and board["fog"] and c.get("kind") != "pj" and not mine
                    and not lit(pos, pos.get("size", 1))):
                continue
        portrait = sheet or sheets.get(c.get("source_id"))
        item = {
            "uid": uid,
            "name": c.get("name") or "?",
            "kind": c.get("kind") or "criatura",
            "turn": index == state.get("turn_index"),
            "mine": mine and not is_master,  # o selo "sua ficha" só faz sentido para jogador
            "can_move": is_master or (mine and board["players_move"] and not hidden),
            "avatar": _avatar(portrait.avatar_url) if portrait else "",
            # Deslocamento da ficha em quadrados, para a régua de movimento.
            "speed": parse_speed(((portrait.data or {}).get("meta") or {}).get("deslocamento"),
                                 board["cell_size"]) if portrait else None,
            "conditions": [x.get("name") for x in c.get("conditions") or []],
        }
        if "hp" in c:
            item["hp"] = to_int(c.get("hp"), 0)
            item["hp_max"] = to_int(c.get("hp_max"), 0)
        else:
            item["health"] = c.get("health")
        if pos:
            item.update(x=pos["x"], y=pos["y"], size=pos.get("size", 1))
            if is_master:
                item["hidden"] = hidden
            tokens.append(item)
        elif is_master or mine:
            bench.append(item)

    markers = []
    for mid, marker in board["markers"].items():
        if not is_master and (marker["hidden"] or (
                board["fog"] and not is_revealed(board, marker["x"] + 0.5, marker["y"] + 0.5))):
            continue
        item = dict(marker, id=mid, icon=MARKER_TYPES[marker["type"]])
        if not is_master:
            item.pop("hidden", None)
        markers.append(item)

    asset = maps.get(board["map_id"])
    map_url = asset.url if asset else None
    if asset and board["fog"] and not is_master:
        # Com névoa, o jogador recebe a imagem já recortada no servidor: o que
        # não foi revelado nem chega ao navegador dele.
        map_url = url_for("campaigns.board_image", campaign_id=encounter.campaign_id,
                          encounter_id=encounter.id, v=fog_key(board))
    payload = {
        "ok": True,
        "version": board["version"],
        "round_number": state.get("round_number"),
        "map_url": map_url,
        "map_title": asset.title if asset else "",
        "cols": board["cols"],
        "rows": board["rows"],
        "grid": board["grid"],
        "cell_size": board["cell_size"],
        "cell_unit": board["cell_unit"],
        "fog": board["fog"],
        "players_move": board["players_move"],
        "revealed": board["revealed"] if board["fog"] else [],
        "fog_layer": board["fog_layer"] if board["fog"] else {"base": "reveal", "strokes": []},
        "brush": MAX_BRUSH,
        "tokens": tokens,
        "bench": bench,
        "markers": markers,
        "areas": board["areas"],
        "marker_types": MARKER_TYPES,
        "user_id": getattr(user, "id", None),
        "is_master": bool(is_master),
    }
    if is_master:
        payload["map_id"] = board["map_id"]
        payload["maps"] = [{"id": a.id, "title": a.title or "Mapa %d" % a.id,
                            "hidden": a.visibility != "mesa"} for a in maps.values()]
    return payload
