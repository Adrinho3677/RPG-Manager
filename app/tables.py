# -*- coding: utf-8 -*-
"""Tabelas aleatórias do mestre ("Encontros na estrada", "Nomes de taverna").

Cada linha do texto vira uma entrada:
    1-3: Lobos famintos      faixa do dado
    4: Bandidos              um número só
    Chuva forte              sem número: pega o próximo depois da linha anterior

O dado da tabela é o maior número usado (uma tabela 1-3/4/5-6 rola 1d6).
Números sem entrada (buracos) dão "nada acontece" — às vezes é de propósito.
"""
import re

from app import dice

MAX_ENTRIES = 200
MAX_TEXT = 300
MAX_SIDE = 1000
_LINE = re.compile(r"^\s*(\d+)\s*(?:[-–a]\s*(\d+))?\s*[:.)\-–]\s*(.+)$")


class TableError(ValueError):
    pass


def parse(text):
    entries, next_value = [], 1
    for number, raw in enumerate((text or "").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        match = _LINE.match(line)
        if match:
            low = int(match.group(1))
            high = int(match.group(2) or low)
            body = match.group(3).strip()
        else:
            low = high = next_value
            body = line
        if low < 1 or high < low:
            raise TableError("Linha %d: faixa inválida (%d-%d)." % (number, low, high))
        if high > MAX_SIDE:
            raise TableError("Linha %d: o dado vai até %d." % (number, MAX_SIDE))
        for other in entries:
            if low <= other["max"] and high >= other["min"]:
                raise TableError("Linha %d: %d-%d cruza com “%s” (%d-%d)."
                                 % (number, low, high, other["text"][:30], other["min"], other["max"]))
        entries.append({"min": low, "max": high, "text": body[:MAX_TEXT]})
        next_value = high + 1
        if len(entries) > MAX_ENTRIES:
            raise TableError("No máximo %d linhas." % MAX_ENTRIES)
    if not entries:
        raise TableError("A tabela precisa de pelo menos uma linha.")
    return sorted(entries, key=lambda e: e["min"])


def as_text(entries):
    """Volta para o texto editável."""
    lines = []
    for entry in entries or []:
        prefix = str(entry["min"]) if entry["min"] == entry["max"] else "%d-%d" % (entry["min"], entry["max"])
        lines.append("%s: %s" % (prefix, entry["text"]))
    return "\n".join(lines)


def die_size(entries):
    return max((e["max"] for e in entries or []), default=1)


def roll(entries):
    sides = die_size(entries)
    value = dice.die(sides) if sides > 1 else 1
    for entry in entries:
        if entry["min"] <= value <= entry["max"]:
            return value, sides, entry["text"]
    return value, sides, "(nada acontece)"
