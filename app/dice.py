# -*- coding: utf-8 -*-
"""Rolagens feitas no servidor.

Numa campanha, os dados rolam aqui e não no navegador: o que chega na mesa é o
que o servidor sorteou, e ninguém consegue mandar um 20 natural pelo console.
Usa o módulo secrets, não random.

Convenção dos parâmetros:
    dice   quantidade de dados (nas paradas) ou quantos d20 rolar (Ordem)
    bonus  soma fixa no resultado; nas paradas, dados extras
    target valor alvo do d100 (Chamado de Cthulhu)
"""
import re
import secrets

MAX_DICE = 100
MAX_SIDES = 1000

ROLL_TYPES = ("d20_mod", "keep_highest_d20", "d100_under", "pool_d10", "d6_pool")

_FORMULA = re.compile(r"^\s*(\d*)\s*d\s*(\d+)\s*(?:([+-])\s*(\d+))?\s*$", re.I)


class DiceError(ValueError):
    pass


def die(sides):
    return secrets.randbelow(sides) + 1


def _signed(bonus):
    if not bonus:
        return ""
    return " %s %d" % ("+" if bonus > 0 else "-", abs(bonus))


def roll_check(roll_type, dice=1, bonus=0, target=None, success_on=6):
    """Rola um teste seguindo a regra do sistema. Devolve result, detail e flag."""
    dice = max(0, min(MAX_DICE, int(dice or 0)))
    bonus = max(-MAX_DICE * 10, min(MAX_DICE * 10, int(bonus or 0)))

    if roll_type == "keep_highest_d20":
        if dice == 0:
            # Atributo zero: rola 2d20 e fica com o pior.
            faces = [die(20), die(20)]
            best = min(faces)
            label = "2d20 (pior)"
        else:
            faces = [die(20) for _ in range(dice)]
            best = max(faces)
            label = "%dd20 (maior)" % dice
        flag = "crit" if best == 20 else ("fail" if best == 1 else "")
        return {
            "result": best + bonus,
            "detail": "%s [%s]%s" % (label, ", ".join(map(str, faces)), _signed(bonus)),
            "flag": flag,
        }

    if roll_type == "d100_under":
        value = die(100)
        limit = int(target if target is not None else bonus)
        if value <= -(-limit // 5):  # ceil(limit/5), igual ao Math.ceil do JS
            quality = "EXTREMO"
        elif value <= limit // 2:
            quality = "BOM"
        elif value <= limit:
            quality = "NORMAL"
        else:
            quality = "FALHA"
        flag = "crit" if value <= limit else "fail"
        if value == 1:
            flag = "crit"
        if value >= 96:
            flag = "fail"
        return {
            "result": value,
            "detail": "1d100 = %d · alvo %d · %s" % (value, limit, quality),
            "flag": flag,
        }

    if roll_type in ("pool_d10", "d6_pool"):
        sides = 10 if roll_type == "pool_d10" else 6
        floor = int(success_on or 6) if roll_type == "pool_d10" else 5
        count = max(1, min(MAX_DICE, dice + bonus))
        faces = [die(sides) for _ in range(count)]
        successes = len([f for f in faces if f >= floor])
        tops = len([f for f in faces if f == sides])
        # Cada par de dez vale dois sucessos extras (crítico).
        successes += (tops // 2) * 2
        flag = "crit" if tops >= 2 else ("fail" if successes == 0 else "")
        return {
            "result": successes,
            "detail": "%dd%d [%s] · sucesso em %d+" % (count, sides, ", ".join(map(str, faces)), floor),
            "flag": flag,
        }

    # d20_mod e qualquer tipo desconhecido
    face = die(20)
    flag = "crit" if face == 20 else ("fail" if face == 1 else "")
    return {
        "result": face + bonus,
        "detail": "1d20 [%d]%s" % (face, _signed(bonus)),
        "flag": flag,
    }


def roll_formula(text):
    """Rola uma fórmula livre como 2d6+3."""
    match = _FORMULA.match(text or "")
    if not match:
        raise DiceError("Use algo como 2d6+3.")
    count = int(match.group(1) or 1)
    sides = int(match.group(2))
    bonus = int(match.group(4) or 0) * (-1 if match.group(3) == "-" else 1)
    if not 1 <= count <= MAX_DICE:
        raise DiceError("Role entre 1 e %d dados." % MAX_DICE)
    if not 2 <= sides <= MAX_SIDES:
        raise DiceError("O dado precisa ter entre 2 e %d lados." % MAX_SIDES)
    faces = [die(sides) for _ in range(count)]
    return {
        "result": sum(faces) + bonus,
        "detail": "%dd%d [%s]%s" % (count, sides, ", ".join(map(str, faces)), _signed(bonus)),
        "flag": "",
    }
