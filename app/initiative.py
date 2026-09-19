# -*- coding: utf-8 -*-
"""Iniciativa de cada sistema, para rolar a de todo mundo com um botão.

No sistema (GameSystem.data["initiative"]):
    source   "skill" (uma perícia), "attribute" (um atributo) ou "formula"
    key      chave da perícia/atributo (aceita também o nome ou a sigla)
    formula  usada quando source = "formula" (ex.: "DES + RAC")
    roll     True rola dados do jeito do sistema; False usa o valor puro
             (Chamado de Cthulhu age por ordem de DES, sem rolar)

A rolagem segue a regra do próprio sistema: em Ordem Paranormal rola
[AGI]d20 e fica com o maior + Iniciativa; em D&D, 1d20 + mod. de Destreza.
"""
from app import dice
from app import formula as formula_helper
from app import sheet as sheet_helper
from app.utils import slugify, to_int

SOURCES = (("skill", "Uma perícia"), ("attribute", "Um atributo"), ("formula", "Uma fórmula"))

ROLLING_TYPES = ("d20_mod", "keep_highest_d20")


def spec_of(system):
    """A regra do sistema; sem regra, o primeiro atributo com 1d20."""
    data = system.data or {}
    spec = data.get("initiative")
    if isinstance(spec, dict) and spec.get("source") in dict(SOURCES):
        return spec
    first = (data.get("attributes") or [{}])[0].get("key", "")
    return {"source": "attribute", "key": first, "roll": True}


def clean(raw, system_data):
    """Valida a regra vinda do editor de sistemas."""
    raw = raw if isinstance(raw, dict) else {}
    source = raw.get("source") if raw.get("source") in dict(SOURCES) else "attribute"
    spec = {"source": source, "roll": bool(raw.get("roll", True))}
    if source == "formula":
        spec["formula"] = str(raw.get("formula") or "").strip()[:120]
    else:
        spec["key"] = str(raw.get("key") or "").strip()[:60]
    return spec


def _find(entries, wanted, *fields):
    wanted_slug = slugify(wanted)
    for entry in entries:
        for field in fields:
            value = str(entry.get(field) or "")
            if value and (value == wanted or slugify(value) == wanted_slug):
                return entry
    return None


def roll_for(character, system):
    """Iniciativa de uma ficha: {result, detail, tiebreak}."""
    spec = spec_of(system)
    roll_type = ((system.data or {}).get("roll") or {}).get("type", "d20_mod")
    built = sheet_helper.build(character)
    count, bonus, source_label = 1, 0, ""

    if spec["source"] == "skill":
        skill = _find(built["skills"], spec.get("key", ""), "key", "name")
        if skill is not None:
            count, bonus, source_label = skill["dice"], skill["total"], skill["name"]
    elif spec["source"] == "attribute":
        attr = _find(built["attributes"], spec.get("key", ""), "key", "abbr", "name")
        if attr is not None:
            value = attr["effective"]
            source_label = attr["abbr"] or attr["name"]
            if roll_type == "keep_highest_d20":
                count, bonus = value, 0
            else:
                bonus = value
    else:
        data, _ = sheet_helper.apply_formulas(system, character.data)
        variables = formula_helper.character_variables(
            sheet_helper.attribute_entries(system, data), data.get("meta"))
        try:
            bonus = int(formula_helper.evaluate(spec.get("formula") or "0", variables))
        except formula_helper.FormulaError:
            bonus = 0
        source_label = spec.get("formula") or ""

    if spec.get("roll", True) and roll_type in ROLLING_TYPES:
        outcome = dice.roll_check(roll_type, dice=count, bonus=bonus)
        return {"result": to_int(outcome["result"], 0), "detail": outcome["detail"],
                "tiebreak": bonus}
    return {"result": bonus, "detail": "%s = %d" % (source_label or "valor", bonus),
            "tiebreak": bonus}
