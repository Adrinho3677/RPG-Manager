# -*- coding: utf-8 -*-
"""Tesouro do grupo: itens e moedas da mesa, separados das fichas.

Nada aqui mexe no inventário ou nas moedas pessoais. "Dividir" e "entregar"
tiram do tesouro e registram quem recebeu quanto; cada jogador anota na própria
ficha. Assim ninguém tem a ficha alterada sem ver.

Campaign.treasure (JSON):
    items  [{id, name, qty, weight, value, note}]
    coins  {chave_da_moeda: quantidade}
    log    [{at, who, text}]   — as 40 últimas movimentações
"""
import secrets
from datetime import datetime

from app.utils import to_float, to_int

MAX_ITEMS = 300
MAX_LOG = 40
MAX_AMOUNT = 10 ** 12


class TreasureError(ValueError):
    pass


def currencies(system):
    coins = [c for c in (system.data or {}).get("currencies") or [] if c.get("key")]
    return coins or [{"key": "moedas", "name": "Moedas", "abbr": ""}]


def normalize(raw):
    raw = raw if isinstance(raw, dict) else {}
    items = []
    for item in raw.get("items") or []:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            continue
        items.append({
            "id": str(item.get("id") or secrets.token_hex(4))[:16],
            "name": str(item["name"]).strip()[:120],
            "qty": max(0, min(MAX_AMOUNT, to_int(item.get("qty"), 1))),
            "weight": max(0.0, to_float(item.get("weight"), 0.0)),
            "value": str(item.get("value") or "").strip()[:60],
            "note": str(item.get("note") or "").strip()[:200],
        })
    coins = {}
    for key, amount in (raw.get("coins") or {}).items():
        coins[str(key)[:40]] = max(0, min(MAX_AMOUNT, to_int(amount, 0)))
    log = [entry for entry in raw.get("log") or [] if isinstance(entry, dict)][:MAX_LOG]
    return {"items": items[:MAX_ITEMS], "coins": coins, "log": log}


def _log(treasure, who, text):
    treasure["log"].insert(0, {"at": datetime.utcnow().isoformat() + "Z", "who": who,
                               "text": text[:300]})
    del treasure["log"][MAX_LOG:]


def _item(treasure, item_id):
    for item in treasure["items"]:
        if item["id"] == item_id:
            return item
    raise TreasureError("Esse item não está mais no tesouro.")


def _coin_label(coins, key):
    for coin in coins:
        if coin["key"] == key:
            return coin.get("abbr") or coin.get("name") or key
    return key


def apply(treasure, payload, who, coins, party):
    """Uma operação vinda da tela. `coins`: moedas do sistema; `party`: {id: nome} dos PJs."""
    op = payload.get("op")
    keys = {c["key"] for c in coins}

    if op == "add_item":
        name = str(payload.get("name") or "").strip()[:120]
        if not name:
            raise TreasureError("Dê um nome ao item.")
        if len(treasure["items"]) >= MAX_ITEMS:
            raise TreasureError("O tesouro já tem itens demais.")
        qty = max(1, min(MAX_AMOUNT, to_int(payload.get("qty"), 1)))
        treasure["items"].append({
            "id": secrets.token_hex(4), "name": name, "qty": qty,
            "weight": max(0.0, to_float(payload.get("weight"), 0.0)),
            "value": str(payload.get("value") or "").strip()[:60],
            "note": str(payload.get("note") or "").strip()[:200],
        })
        _log(treasure, who, "guardou %d× %s" % (qty, name))

    elif op == "update_item":
        item = _item(treasure, str(payload.get("id")))
        if "name" in payload and str(payload["name"]).strip():
            item["name"] = str(payload["name"]).strip()[:120]
        if "qty" in payload:
            item["qty"] = max(0, min(MAX_AMOUNT, to_int(payload.get("qty"), item["qty"])))
        if "weight" in payload:
            item["weight"] = max(0.0, to_float(payload.get("weight"), item["weight"]))
        for key, limit in (("value", 60), ("note", 200)):
            if key in payload:
                item[key] = str(payload.get(key) or "").strip()[:limit]

    elif op == "remove_item":
        item = _item(treasure, str(payload.get("id")))
        treasure["items"].remove(item)
        _log(treasure, who, "tirou %s do tesouro" % item["name"])

    elif op == "give_item":
        item = _item(treasure, str(payload.get("id")))
        target = party.get(to_int(payload.get("to"), 0))
        if target is None:
            raise TreasureError("Escolha um personagem do grupo.")
        qty = max(1, to_int(payload.get("qty"), 1))
        if qty > item["qty"]:
            raise TreasureError("Só há %d× %s no tesouro." % (item["qty"], item["name"]))
        item["qty"] -= qty
        if item["qty"] == 0:
            treasure["items"].remove(item)
        _log(treasure, who, "entregou %d× %s a %s" % (qty, item["name"], target))

    elif op == "coins":
        deltas = payload.get("deltas") or {}
        changes = []
        for key, raw in deltas.items():
            if key not in keys:
                continue
            delta = to_int(raw, 0)
            if not delta:
                continue
            current = treasure["coins"].get(key, 0)
            if current + delta < 0:
                raise TreasureError("Não há %s suficiente: o tesouro tem %d."
                                    % (_coin_label(coins, key), current))
            treasure["coins"][key] = min(MAX_AMOUNT, current + delta)
            changes.append("%s%d %s" % ("+" if delta > 0 else "", delta, _coin_label(coins, key)))
        if not changes:
            raise TreasureError("Nada para mudar.")
        reason = str(payload.get("reason") or "").strip()[:120]
        _log(treasure, who, ", ".join(changes) + (" — " + reason if reason else ""))

    elif op == "split":
        chosen = [cid for cid in (to_int(x, 0) for x in payload.get("characters") or [])
                  if cid in party]
        chosen = list(dict.fromkeys(chosen))
        if not chosen:
            raise TreasureError("Escolha quem entra na divisão.")
        wanted = [k for k in (payload.get("coins") or list(keys)) if k in keys]
        shares = split_preview(treasure, coins, len(chosen), wanted)
        if not any(s["each"] for s in shares):
            raise TreasureError("Não há moedas suficientes para dividir entre %d." % len(chosen))
        parts = []
        for share in shares:
            if not share["each"]:
                continue
            treasure["coins"][share["key"]] -= share["each"] * len(chosen)
            parts.append("%d %s" % (share["each"], share["label"]))
        leftover = ["%d %s" % (s["left"], s["label"]) for s in shares if s["left"]]
        names = ", ".join(party[cid] for cid in chosen)
        _log(treasure, who, "dividiu entre %s: %s para cada um%s"
             % (names, " + ".join(parts),
                " (sobrou " + ", ".join(leftover) + " no tesouro)" if leftover else ""))
    else:
        raise TreasureError("Operação desconhecida.")
    return treasure


def split_preview(treasure, coins, people, keys=None):
    """Quanto cada um recebe e quanto sobra, por moeda."""
    out = []
    for coin in coins:
        if keys is not None and coin["key"] not in keys:
            continue
        total = treasure["coins"].get(coin["key"], 0)
        each = total // people if people else 0
        out.append({"key": coin["key"], "label": coin.get("abbr") or coin.get("name"),
                    "each": each, "left": total - each * people})
    return out


def total_weight(treasure):
    return round(sum(i["qty"] * i["weight"] for i in treasure["items"]), 2)
