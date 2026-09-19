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



class DiceError(ValueError):
    pass


def die(sides):
    return secrets.randbelow(sides) + 1


def _signed(bonus):
    if not bonus:
        return ""
    return " %s %d" % ("+" if bonus > 0 else "-", abs(bonus))


MODES = ("", "vantagem", "desvantagem")


def roll_check(roll_type, dice=1, bonus=0, target=None, success_on=6, mode=""):
    """Rola um teste seguindo a regra do sistema. Devolve result, detail e flag.

    mode "vantagem"/"desvantagem" segue o jeito de cada sistema: em d20, rola
    dois e fica com o maior/menor; em Ordem e nas paradas, um dado a mais/a
    menos; no d100, dois d100 e fica com o melhor/pior.
    """
    dice = max(0, min(MAX_DICE, int(dice or 0)))
    bonus = max(-MAX_DICE * 10, min(MAX_DICE * 10, int(bonus or 0)))
    mode = mode if mode in MODES else ""
    if mode and roll_type == "keep_highest_d20":
        dice = dice + 1 if mode == "vantagem" else max(0, dice - 1)
    elif mode and roll_type in ("pool_d10", "d6_pool"):
        bonus = bonus + 1 if mode == "vantagem" else bonus - 1
    elif mode and roll_type == "d100_under":
        first = roll_check(roll_type, dice, bonus, target, success_on)
        second = roll_check(roll_type, dice, bonus, target, success_on)
        pick = min if mode == "vantagem" else max
        chosen = pick((first, second), key=lambda r: r["result"])
        other = second if chosen is first else first
        chosen = dict(chosen)
        chosen["detail"] = "%s · %s (%d descartado)" % (chosen["detail"], mode, other["result"])
        return chosen
    elif mode:  # d20_mod
        a, b = die(20), die(20)
        face = max(a, b) if mode == "vantagem" else min(a, b)
        flag = "crit" if face == 20 else ("fail" if face == 1 else "")
        return {"result": face + bonus,
                "detail": "2d20 %s [%d, %d]%s" % (mode, a, b, _signed(bonus)), "flag": flag}

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


# ------------------------------------------------------------ fórmulas livres
MAX_TERMS = 20
MAX_EXPLOSIONS = 100
_TOKEN = re.compile(r"\s*(?:(?P<dice>(?P<count>\d*)d(?P<sides>\d+|%)(?:(?P<keep>k[hl]?|kl)(?P<keepn>\d+))?(?P<bang>!)?)"
                    r"|(?P<num>\d+)|(?P<name>[A-Za-zÀ-ÿ_][A-Za-zÀ-ÿ0-9_]*)|(?P<op>[+-]))", re.I)


def _roll_dice(count, sides, keep, keep_n, explode, budget):
    """Rola um termo NdM[khK|klK][!]. Devolve (soma, texto, faces de d20 mantidas)."""
    if not 1 <= count <= MAX_DICE:
        raise DiceError("Role entre 1 e %d dados por termo." % MAX_DICE)
    if not 2 <= sides <= MAX_SIDES:
        raise DiceError("O dado precisa ter entre 2 e %d lados." % MAX_SIDES)
    faces = []
    for _ in range(count):
        face = die(sides)
        chain = [face]
        # Dado que explode: tirou o máximo, rola de novo e soma (com limite).
        while explode and face == sides and budget[0] < MAX_EXPLOSIONS:
            budget[0] += 1
            face = die(sides)
            chain.append(face)
        faces.append(chain)
    totals = [sum(chain) for chain in faces]
    kept = list(range(len(faces)))
    if keep:
        keep_n = max(1, min(count, keep_n))
        order = sorted(range(len(totals)), key=lambda i: totals[i], reverse=(keep != "kl"))
        kept = sorted(order[:keep_n])
    shown = []
    for i, chain in enumerate(faces):
        text = "+".join(map(str, chain)) + ("!" if len(chain) > 1 else "")
        shown.append(text if i in kept else "(%s)" % text)  # entre parênteses: descartado
    label = "%dd%d%s%s" % (count, sides, (keep + str(keep_n)) if keep else "", "!" if explode else "")
    d20s = [totals[i] for i in kept] if sides == 20 else []
    return sum(totals[i] for i in kept), "%s [%s]" % (label, ", ".join(shown)), d20s


def roll_formula(text, variables=None):
    """Rola uma fórmula livre.

    Aceita: 2d6+3 · 1d20+1d4+2 · 2d20kh1 (vantagem) · 2d20kl1 (desvantagem) ·
    4d6kh3 · 3d6! (explode) · d% · e, rolando de uma ficha, siglas e nomes de
    atributos: 1d20+FOR, 1d8+DES+2.
    """
    text = (text or "").strip()
    if not text or len(text) > 80:
        raise DiceError("Use algo como 2d6+3.")
    lookup = {str(k).lower(): v for k, v in (variables or {}).items()}
    total, parts, d20s, sign, terms, pos = 0, [], [], 1, 0, 0
    expect_term, budget = True, [0]
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            raise DiceError("Não entendi “%s”. Use algo como 2d6+3." % text[pos:pos + 10].strip())
        pos = match.end()
        if match.group("op"):
            if expect_term:
                if match.group("op") == "-":
                    sign = -sign
                continue
            sign = -1 if match.group("op") == "-" else 1
            expect_term = True
            continue
        if not expect_term:
            raise DiceError("Falta um + ou - entre os termos.")
        terms += 1
        if terms > MAX_TERMS:
            raise DiceError("Fórmula grande demais.")
        if match.group("dice"):
            sides_raw = match.group("sides")
            sides = 100 if sides_raw == "%" else int(sides_raw)
            keep = (match.group("keep") or "").lower()
            keep = {"k": "kh", "kh": "kh", "kl": "kl"}.get(keep, "")
            value, detail, kept20 = _roll_dice(int(match.group("count") or 1), sides, keep,
                                               int(match.group("keepn") or 0),
                                               bool(match.group("bang")), budget)
            if sign > 0:
                d20s.extend(kept20)
        elif match.group("num"):
            value = int(match.group("num"))
            detail = str(value)
        else:
            name = match.group("name")
            if name.lower() not in lookup:
                raise DiceError("Não conheço “%s”%s. Use algo como 2d6+3%s." % (
                    name, " nesta ficha" if variables else " (siglas só valem rolando de uma ficha)",
                    " ou 1d20+" + next(iter(k for k in (variables or {}) if k.isupper()), "FOR")
                    if variables else ""))
            value = int(lookup[name.lower()])
            detail = "%s(%d)" % (name.upper(), value)
        total += sign * value
        parts.append(("- " if sign < 0 else ("+ " if parts else "")) + detail)
        sign, expect_term = 1, False
    if expect_term:
        raise DiceError("A fórmula terminou num + ou -.")
    flag = ""
    if len(d20s) == 1:  # um d20 decisivo: 20 natural é crítico, 1 é falha
        flag = "crit" if d20s[0] == 20 else ("fail" if d20s[0] == 1 else "")
    return {"result": total, "detail": " ".join(parts), "flag": flag}
