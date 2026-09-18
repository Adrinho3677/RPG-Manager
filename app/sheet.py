# -*- coding: utf-8 -*-
"""Monta a ficha combinando o modelo do sistema com os campos extras que o
jogador adicionou naquele personagem específico."""

import copy

from app import formula
from app.utils import ability_modifier, to_float, to_int

EMPTY_SHEET = {
    "attributes": {},
    "skills": {},
    "bars": {},
    "meta": {},
    "money": {},
    "custom": {"attributes": [], "bars": [], "skills": [], "meta_fields": []},
    "inventory": [],
    "abilities": [],
    "attacks": [],
    "spells": [],
    "conditions": [],
    "progress": [],
    "xp": 0,
    "notes": "",
    "history": "",
    "appearance": "",
}

DEFAULT_INVENTORY = {
    "mode": "none",
    "unit": "kg",
    "capacity_base": 0,
    "capacity_attr": "",
    "capacity_per_point": 0,
    "overload_multiplier": 2.0,
}

DEFAULT_LABELS = {
    "attacks": "Ataques",
    "spells": "Magias",
    "spell_level": "Círculo",
    "abilities": "Habilidades",
}


def normalize(data):
    """Garante que todas as chaves esperadas existam."""
    data = dict(data or {})
    for key, default in EMPTY_SHEET.items():
        if key not in data or data[key] is None:
            data[key] = type(default)() if not isinstance(default, str) else default
    custom = dict(data.get("custom") or {})
    for key in ("attributes", "bars", "skills", "meta_fields"):
        custom.setdefault(key, [])
    data["custom"] = custom
    return data


def merged_defs(system, data):
    """Definições do sistema + as criadas dentro da ficha (marcadas custom)."""
    data = normalize(data)
    custom = data["custom"]

    def tag(items, is_custom):
        out = []
        for item in items or []:
            entry = dict(item)
            entry["custom"] = is_custom
            out.append(entry)
        return out

    return {
        "attributes": tag(system.attributes, False) + tag(custom["attributes"], True),
        "bars": tag(system.bars, False) + tag(custom["bars"], True),
        "skills": tag(system.skills, False) + tag(custom["skills"], True),
        "meta_fields": tag(system.meta_fields, False) + tag(custom["meta_fields"], True),
    }


def effective_attr(value, display):
    """Valor do atributo usado nas contas de rolagem."""
    if display == "modifier":
        return ability_modifier(value)
    return to_int(value)


def attribute_entries(system, data):
    """Atributos com valor e valor efetivo, sem montar a ficha inteira."""
    sysdata = system.data or {}
    display = sysdata.get("attribute_display", "number")
    entries = []
    for d in merged_defs(system, data)["attributes"]:
        raw = (data.get("attributes") or {}).get(d["key"], d.get("default", 0))
        value = to_int(raw, to_int(d.get("default", 0)))
        entries.append({
            "key": d["key"],
            "abbr": d.get("abbr", ""),
            "name": d.get("name", d["key"]),
            "value": value,
            "effective": effective_attr(value, display),
        })
    return entries


def apply_formulas(system, data):
    """Recalcula o máximo das barras que têm fórmula.

    Devolve (data, erros), onde erros é {chave_da_barra: mensagem}. Se o máximo
    cair abaixo do valor atual, o atual acompanha; se subir, o atual fica onde
    está — ganhar vida máxima não cura ninguém.
    """
    # Cópia profunda: normalize() é rasa, e sem isso as barras do próprio
    # objeto do personagem seriam alteradas no lugar.
    data = normalize(copy.deepcopy(data))
    variables = formula.character_variables(attribute_entries(system, data), data.get("meta"))
    errors = {}

    for bar in merged_defs(system, data)["bars"]:
        expression = (bar.get("max_formula") or "").strip()
        if not expression:
            continue
        try:
            maximum = max(0, formula.evaluate(expression, variables))
        except formula.FormulaError as error:
            errors[bar["key"]] = str(error)
            continue
        stored = dict(data["bars"].get(bar["key"]) or {})
        current = to_int(stored.get("current", maximum), maximum)
        stored["max"] = maximum
        stored["current"] = min(current, maximum)
        stored.setdefault("temp", 0)
        data["bars"][bar["key"]] = stored

    return data, errors


def carry_load(inv_config, items, attributes_by_key):
    """Calcula peso/espaços usados e a capacidade do personagem."""
    config = dict(DEFAULT_INVENTORY)
    config.update(inv_config or {})
    mode = config.get("mode", "none")

    used = 0.0
    for item in items or []:
        qty = to_int(item.get("qty"), 1)
        used += to_float(item.get("weight"), 0) * max(qty, 0)

    attr = attributes_by_key.get(config.get("capacity_attr"))
    # A capacidade usa o valor cru do atributo: em D&D é a Força (15 kg por
    # ponto) e em Tormenta o próprio modificador já é o valor guardado.
    attr_value = attr["value"] if attr else 0
    capacity = to_float(config.get("capacity_base"), 0) + attr_value * to_float(
        config.get("capacity_per_point"), 0
    )
    overload = to_float(config.get("overload_multiplier"), 2.0) or 2.0
    hard_limit = capacity * overload

    if capacity <= 0:
        percent, state, label = 0, "ok", ""
    else:
        percent = max(0, min(100, int(used * 100 / capacity)))
        if used > hard_limit:
            state, label = "over", "Acima do limite"
        elif used > capacity:
            state, label = "warn", "Sobrecarregado"
        else:
            state, label = "ok", "Dentro do limite"

    return {
        "mode": mode,
        "unit": config.get("unit", "kg"),
        "used": used,
        "capacity": capacity,
        "hard_limit": hard_limit,
        "percent": percent,
        "state": state,
        "label": label,
        "attr": config.get("capacity_attr", ""),
        "attr_name": attr["name"] if attr else "",
        "base": to_float(config.get("capacity_base"), 0),
        "per_point": to_float(config.get("capacity_per_point"), 0),
        "overload": overload,
    }


REST_MODES = [
    ("none", "Não recupera"),
    ("full", "Recupera tudo"),
    ("half", "Metade do máximo"),
    ("amount", "Soma X pontos"),
    ("percent", "Soma X% do máximo"),
]

DEFAULT_REST = {"short": {"mode": "none", "value": 0}, "long": {"mode": "full", "value": 0}}


def rest_rule(bar_def, kind):
    """Regra de descanso de uma barra, com padrão para barras criadas na ficha."""
    rule = bar_def.get("rest_%s" % kind)
    if not isinstance(rule, dict):
        rule = DEFAULT_REST[kind]
    mode = rule.get("mode", "none")
    if mode not in dict(REST_MODES):
        mode = "none"
    return {"mode": mode, "value": to_int(rule.get("value"), 0)}


def rest_label(rule):
    if rule["mode"] == "amount":
        return "+%d" % rule["value"]
    if rule["mode"] == "percent":
        return "+%d%%" % rule["value"]
    return dict(REST_MODES)[rule["mode"]]


def apply_rest(system, data, kind):
    """Aplica um descanso às barras. Devolve o que mudou, para avisar o jogador."""
    data, _ = apply_formulas(system, data)
    defs = merged_defs(system, data)
    changes = []

    for bar in defs["bars"]:
        key = bar["key"]
        rule = rest_rule(bar, kind)
        if rule["mode"] == "none" and kind != "long":
            continue

        stored = dict(data["bars"].get(key) or {})
        maximum = to_int(stored.get("max", bar.get("default_max", 10)), 10)
        before = to_int(stored.get("current", maximum), maximum)

        if rule["mode"] == "full":
            after = maximum
        elif rule["mode"] == "half":
            after = min(maximum, before + maximum // 2)
        elif rule["mode"] == "amount":
            after = min(maximum, before + rule["value"])
        elif rule["mode"] == "percent":
            after = min(maximum, before + int(maximum * rule["value"] / 100))
        else:
            after = before

        # Pontos temporários não sobrevivem a um descanso longo.
        temp_before = to_int(stored.get("temp", 0))
        temp_after = 0 if kind == "long" else temp_before

        if after == before and temp_after == temp_before:
            continue

        stored["current"] = after
        stored["temp"] = temp_after
        data["bars"][key] = stored

        if after != before:
            changes.append("%s %+d (agora %d/%d)" % (bar.get("abbr") or bar["name"],
                                                     after - before, after, maximum))
        elif temp_before:
            changes.append("%s perdeu %d temporário" % (bar.get("abbr") or bar["name"],
                                                        temp_before))

    return data, changes


def build(character):
    """Retorna a estrutura pronta para o template da ficha."""
    system = character.system
    sysdata = system.data or {}
    data, formula_errors = apply_formulas(system, character.data)
    defs = merged_defs(system, data)

    display = sysdata.get("attribute_display", "number")
    skill_mode = sysdata.get("skill_mode", "bonus")
    roll_type = (sysdata.get("roll") or {}).get("type", "d20_mod")
    prof_bonus = to_int((data.get("meta") or {}).get("prof"), 2)

    attributes = []
    attr_lookup = {}
    for d in defs["attributes"]:
        raw = data["attributes"].get(d["key"], d.get("default", 0))
        value = to_int(raw, to_int(d.get("default", 0)))
        eff = effective_attr(value, display)
        entry = {
            "key": d["key"],
            "name": d.get("name", d["key"]),
            "abbr": d.get("abbr", ""),
            "min": to_int(d.get("min", 0)),
            "max": to_int(d.get("max", 10), 10),
            "value": value,
            "effective": eff,
            "modifier": ability_modifier(value) if display == "modifier" else eff,
            "custom": d.get("custom", False),
        }
        attributes.append(entry)
        attr_lookup[d["key"]] = entry

    bars = []
    for d in defs["bars"]:
        stored = data["bars"].get(d["key"]) or {}
        maximum = to_int(stored.get("max", d.get("default_max", 10)), 10)
        current = to_int(stored.get("current", maximum), maximum)
        temp = to_int(stored.get("temp", 0))
        pct = 0 if maximum <= 0 else max(0, min(100, int(current * 100 / maximum)))
        bars.append(
            {
                "key": d["key"],
                "name": d.get("name", d["key"]),
                "abbr": d.get("abbr", ""),
                "color": d.get("color", "#8b5cf6"),
                "formula": d.get("formula", ""),
                "current": current,
                "max": maximum,
                "temp": temp,
                "percent": pct,
                "custom": d.get("custom", False),
                "rest_short": rest_label(rest_rule(d, "short")),
                "rest_long": rest_label(rest_rule(d, "long")),
                "max_formula": (d.get("max_formula") or "").strip(),
                "formula_error": formula_errors.get(d["key"]),
            }
        )

    skills = []
    for d in defs["skills"]:
        stored = data["skills"].get(d["key"]) or {}
        attr_key = d.get("attr")
        attr = attr_lookup.get(attr_key)
        attr_value = attr["effective"] if attr else 0
        base = to_int(stored.get("value", d.get("default", 0)), to_int(d.get("default", 0)))
        train = to_int(stored.get("train", 0))
        prof = to_int(stored.get("prof", 0))
        other = to_int(stored.get("other", 0))

        if skill_mode == "percent":
            total = base + other
            dice = 0
        elif skill_mode == "dots":
            total = attr_value + base + other
            dice = total
        elif skill_mode == "proficiency":
            total = attr_value + prof * prof_bonus + other
            dice = 1
        elif skill_mode == "training":
            if roll_type == "keep_highest_d20":
                total = train + other
                dice = max(1, attr_value)
            else:
                total = attr_value + train + other
                dice = 1
        else:
            total = attr_value + base + other
            dice = 1

        skills.append(
            {
                "key": d["key"],
                "name": d.get("name", d["key"]),
                "attr": attr_key,
                "attr_abbr": attr["abbr"] if attr else "",
                "value": base,
                "train": train,
                "prof": prof,
                "other": other,
                "total": total,
                "dice": dice,
                "custom": d.get("custom", False),
            }
        )
    skills.sort(key=lambda s: s["name"].lower())

    meta = []
    for d in defs["meta_fields"]:
        meta.append(
            {
                "key": d["key"],
                "name": d.get("name", d["key"]),
                "type": d.get("type", "text"),
                "value": data["meta"].get(d["key"], ""),
                "custom": d.get("custom", False),
            }
        )

    labels = dict(DEFAULT_LABELS)
    labels.update(sysdata.get("labels") or {})

    currencies = sysdata.get("currencies") or []
    money = [
        {
            "key": coin["key"],
            "name": coin.get("name", coin["key"]),
            "abbr": coin.get("abbr", ""),
            "value": to_int((data.get("money") or {}).get(coin["key"]), 0),
        }
        for coin in currencies
    ]

    inventory = data.get("inventory") or []
    # Ordem cronológica, sempre: o JS reescreve a lista na ordem em que ela é
    # exibida, então inverter aqui bagunçaria o log a cada salvamento.
    progress = list(data.get("progress") or [])
    spells = sorted(
        data.get("spells") or [], key=lambda s: (to_int(s.get("level"), 0), str(s.get("name", "")))
    )

    return {
        "display": display,
        "skill_mode": skill_mode,
        "roll": sysdata.get("roll", {"type": "d20_mod", "label": "1d20 + modificador"}),
        "training_levels": sysdata.get("training_levels", []),
        "prof_bonus": prof_bonus,
        "labels": labels,
        "attributes": attributes,
        "bars": bars,
        "skills": skills,
        "meta": meta,
        "money": money,
        "inventory": inventory,
        "load": carry_load(sysdata.get("inventory"), inventory, attr_lookup),
        "abilities": data.get("abilities") or [],
        "attacks": data.get("attacks") or [],
        "spells": spells,
        "conditions": data.get("conditions") or [],
        "progress": progress,
        "xp": to_int(data.get("xp"), 0),
        "xp_gained": sum(to_int(entry.get("amount"), 0) for entry in progress),
        "notes": data.get("notes") or "",
        "history": data.get("history") or "",
        "appearance": data.get("appearance") or "",
    }


def blank_data(system):
    """Valores iniciais de uma ficha nova."""
    data = normalize({})
    for attribute in system.attributes:
        data["attributes"][attribute["key"]] = attribute.get("default", 0)
    for bar in system.bars:
        maximum = to_int(bar.get("default_max", 10), 10)
        data["bars"][bar["key"]] = {"current": maximum, "max": maximum, "temp": 0}
    for skill in system.skills:
        data["skills"][skill["key"]] = {
            "value": to_int(skill.get("default", 0)),
            "train": 0,
            "prof": 0,
            "other": 0,
        }
    for field in system.meta_fields:
        data["meta"][field["key"]] = ""
    for coin in (system.data or {}).get("currencies") or []:
        data["money"][coin["key"]] = 0
    data, _ = apply_formulas(system, data)
    # numa ficha nova, a barra começa cheia mesmo quando o máximo vem da fórmula
    for bar in system.bars:
        if (bar.get("max_formula") or "").strip() and bar["key"] in data["bars"]:
            data["bars"][bar["key"]]["current"] = data["bars"][bar["key"]]["max"]
    return data
