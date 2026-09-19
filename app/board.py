# -*- coding: utf-8 -*-
"""Mapa tático de um combate: grade, imagem de fundo, fichas e névoa.

O estado fica em Encounter.board (JSON):

    map_id        Asset (kind "mapa") da campanha usado de fundo, ou None
    cols, rows    tamanho da grade em quadrados
    grid          mostrar as linhas da grade
    cell_size     quanto vale um quadrado (1.5) ...
    cell_unit     ... e em que unidade ("m")
    fog           névoa de guerra ligada
    revealed      quadrados revelados, como "x,y"
    players_move  jogadores podem mover as próprias fichas
    tokens        {uid do combatente: {"x", "y", "hidden"}}
    version       sobe a cada mudança

As fichas do mapa SÃO os combatentes do rastreador (mesmo uid): nada de
cadastro duplicado. Combatente fora de `tokens` está "fora do mapa".

Segredos, como no rastreador: para jogadores, fichas escondidas pelo mestre e
inimigos debaixo da névoa nem entram na resposta.
"""
import json

from sqlalchemy import text

from app.extensions import db
from app.utils import to_float, to_int

MAX_SIDE = 60
DEFAULTS = {
    "map_id": None,
    "cols": 20,
    "rows": 14,
    "grid": True,
    "cell_size": 1.5,
    "cell_unit": "m",
    "fog": False,
    "revealed": [],
    "players_move": True,
    "tokens": {},
    "version": 0,
}


class BoardError(ValueError):
    """Pedido inválido: vira 400 com a mensagem para a pessoa."""


def _clamp(value, low, high):
    return max(low, min(high, value))


def _cell(x, y):
    return "%d,%d" % (x, y)


def normalize(raw):
    """Sempre devolve um tabuleiro completo e dentro dos limites."""
    raw = raw if isinstance(raw, dict) else {}
    board = dict(DEFAULTS)
    board["map_id"] = to_int(raw.get("map_id"), 0) or None
    board["cols"] = _clamp(to_int(raw.get("cols"), DEFAULTS["cols"]), 1, MAX_SIDE)
    board["rows"] = _clamp(to_int(raw.get("rows"), DEFAULTS["rows"]), 1, MAX_SIDE)
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
        if 0 <= x < board["cols"] and 0 <= y < board["rows"]:
            revealed.add(_cell(x, y))
    board["revealed"] = sorted(revealed)

    tokens = {}
    for uid, pos in (raw.get("tokens") or {}).items():
        if not isinstance(pos, dict):
            continue
        tokens[str(uid)[:16]] = {
            "x": _clamp(to_int(pos.get("x"), 0), 0, board["cols"] - 1),
            "y": _clamp(to_int(pos.get("y"), 0), 0, board["rows"] - 1),
            "hidden": bool(pos.get("hidden")),
        }
    board["tokens"] = tokens
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
            board[key] = _clamp(to_int(payload.get(key), board[key]), 1, MAX_SIDE)
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


def move(board, uid, x, y):
    """x/y None tira a ficha do mapa."""
    if x is None or y is None:
        board["tokens"].pop(uid, None)
        return board
    x, y = to_int(x, -1), to_int(y, -1)
    if not (0 <= x < board["cols"] and 0 <= y < board["rows"]):
        raise BoardError("Fora do mapa.")
    current = board["tokens"].get(uid) or {}
    board["tokens"][uid] = {"x": x, "y": y, "hidden": bool(current.get("hidden"))}
    return board


def set_hidden(board, uid, hidden):
    if uid not in board["tokens"]:
        raise BoardError("Essa ficha não está no mapa.")
    board["tokens"][uid]["hidden"] = bool(hidden)
    return board


def paint_fog(board, cells, reveal):
    """Revela (ou cobre de novo) uma lista de quadrados [[x, y], ...]."""
    revealed = set(board["revealed"])
    for item in (cells or [])[:MAX_SIDE * MAX_SIDE]:
        try:
            x, y = int(item[0]), int(item[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= x < board["cols"] and 0 <= y < board["rows"]:
            (revealed.add if reveal else revealed.discard)(_cell(x, y))
    board["revealed"] = sorted(revealed)
    return board


def fog_all(board, reveal):
    board["revealed"] = ([_cell(x, y) for x in range(board["cols"]) for y in range(board["rows"])]
                         if reveal else [])
    return board


def update(encounter, change):
    """Aplica `change(board)` sem perder a mudança de outra pessoa.

    Mestre e jogadores movem fichas ao mesmo tempo. Ler, alterar e gravar o
    JSON inteiro faria um apagar o movimento do outro; por isso a gravação só
    vale se o tabuleiro ainda for o que foi lido (compare-and-swap), e senão
    tenta de novo em cima do valor novo.
    """
    for _ in range(5):
        raw = db.session.execute(text("SELECT board FROM encounters WHERE id = :id"),
                                 {"id": encounter.id}).scalar()
        try:
            loaded = json.loads(raw) if raw else None
        except ValueError:
            loaded = None
        board = change(normalize(loaded))
        board["version"] += 1
        new_raw = json.dumps(board, ensure_ascii=False)
        if raw is None:
            sql = "UPDATE encounters SET board = :new WHERE id = :id AND board IS NULL"
        else:
            sql = "UPDATE encounters SET board = :new WHERE id = :id AND board = :old"
        result = db.session.execute(text(sql), {"new": new_raw, "old": raw, "id": encounter.id})
        if result.rowcount == 1:
            db.session.commit()
            db.session.expire(encounter, ["board"])
            return board
        db.session.rollback()
    raise BoardError("O mapa está sendo alterado por várias pessoas agora. Tente de novo.")


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

    revealed = set(board["revealed"])
    tokens, bench = [], []
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
                    and _cell(pos["x"], pos["y"]) not in revealed):
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
            "conditions": [x.get("name") for x in c.get("conditions") or []],
        }
        if "hp" in c:
            item["hp"] = to_int(c.get("hp"), 0)
            item["hp_max"] = to_int(c.get("hp_max"), 0)
        else:
            item["health"] = c.get("health")
        if pos:
            item.update(x=pos["x"], y=pos["y"])
            if is_master:
                item["hidden"] = hidden
            tokens.append(item)
        elif is_master or mine:
            bench.append(item)

    asset = maps.get(board["map_id"])
    payload = {
        "ok": True,
        "version": board["version"],
        "round_number": state.get("round_number"),
        "map_url": asset.url if asset else None,
        "map_title": asset.title if asset else "",
        "cols": board["cols"],
        "rows": board["rows"],
        "grid": board["grid"],
        "cell_size": board["cell_size"],
        "cell_unit": board["cell_unit"],
        "fog": board["fog"],
        "players_move": board["players_move"],
        "revealed": board["revealed"] if board["fog"] else [],
        "tokens": tokens,
        "bench": bench,
        "is_master": bool(is_master),
    }
    if is_master:
        payload["map_id"] = board["map_id"]
        payload["maps"] = [{"id": a.id, "title": a.title or "Mapa %d" % a.id,
                            "hidden": a.visibility != "mesa"} for a in maps.values()]
    return payload
