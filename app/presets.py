# -*- coding: utf-8 -*-
"""Modelos de ficha pré-configurados.

Cada preset descreve a estrutura da ficha. O usuário pode duplicar qualquer um
deles e editar livremente atributos, barras, perícias e campos de identidade.

Estrutura de `data`:
    roll               -> como o sistema rola dados (ver static/js/dice.js)
    attribute_display  -> number | modifier | percent | dots
    skill_mode         -> training | proficiency | percent | dots | bonus
    training_levels    -> níveis de treino (usado por skill_mode = training)
    attributes         -> [{key, name, abbr, default, min, max}]
    bars               -> [{key, name, abbr, color, default_max, formula,
                            max_formula, rest_short, rest_long}]
                          max_formula calcula o máximo sozinho (ver app/formula.py)
    skills             -> [{key, name, attr, default}]
    meta_fields        -> [{key, name, type}]  type: text|number|textarea|select
    inventory          -> como funciona a carga (peso, espaços ou nada)
    currencies         -> moedas usadas pelo sistema
    labels             -> nomes das seções (Magias/Rituais/Disciplinas etc.)
"""


def _attr(key, name, abbr, default=1, minimum=0, maximum=5):
    return {"key": key, "name": name, "abbr": abbr, "default": default, "min": minimum, "max": maximum}


def _inv(mode="none", unit="kg", base=0, attr="", per_point=0, overload=2.0):
    """Configuração de carga.

    mode: "weight" (peso), "slots" (espaços) ou "none" (sem controle).
    capacidade = base + valor_do_atributo * per_point
    Acima da capacidade o personagem fica sobrecarregado; acima de
    capacidade * overload ele não consegue mais carregar.
    """
    return {
        "mode": mode,
        "unit": unit,
        "capacity_base": base,
        "capacity_attr": attr,
        "capacity_per_point": per_point,
        "overload_multiplier": overload,
    }


def _coin(key, name, abbr):
    return {"key": key, "name": name, "abbr": abbr}


def _labels(attacks="Ataques", spells="Magias", spell_level="Círculo", abilities="Habilidades"):
    return {
        "attacks": attacks,
        "spells": spells,
        "spell_level": spell_level,
        "abilities": abilities,
    }


def _rest(mode="none", value=0):
    """O que a barra recupera num descanso.

    mode: none (nada) | full (enche) | half (metade do máximo) |
          amount (soma `value` pontos) | percent (soma `value`% do máximo)
    """
    return {"mode": mode, "value": value}


def _bar(key, name, abbr, color, default_max=10, formula="", short="none", long="full",
         max_formula=""):
    return {
        "key": key,
        "name": name,
        "abbr": abbr,
        "color": color,
        "default_max": default_max,
        "formula": formula,
        "max_formula": max_formula,
        "rest_short": short if isinstance(short, dict) else _rest(short),
        "rest_long": long if isinstance(long, dict) else _rest(long),
    }


def _skill(key, name, attr, default=0):
    return {"key": key, "name": name, "attr": attr, "default": default}


def _meta(key, name, ftype="text"):
    return {"key": key, "name": name, "type": ftype}


# ---------------------------------------------------------------- Ordem Paranormal
ORDEM = {
    "roll": {"type": "keep_highest_d20", "label": "Role [atributo]d20, pegue o maior + bônus"},
    "attribute_display": "number",
    "skill_mode": "training",
    "training_levels": [
        {"label": "Destreinado", "value": 0},
        {"label": "Treinado", "value": 5},
        {"label": "Veterano", "value": 10},
        {"label": "Expert", "value": 15},
    ],
    "attributes": [
        _attr("agi", "Agilidade", "AGI", 1, 0, 5),
        _attr("for", "Força", "FOR", 1, 0, 5),
        _attr("int", "Intelecto", "INT", 1, 0, 5),
        _attr("pre", "Presença", "PRE", 1, 0, 5),
        _attr("vig", "Vigor", "VIG", 1, 0, 5),
    ],
    "bars": [
        _bar("pv", "Pontos de Vida", "PV", "#c0392b", 20, short="none", long="full"),
        _bar("pe", "Pontos de Esforço", "PE", "#2980b9", 10, short="none", long="full"),
        _bar("san", "Sanidade", "SAN", "#8e44ad", 12, short="none", long="none"),
    ],
    "skills": [
        _skill("acrobacia", "Acrobacia", "agi"),
        _skill("adestramento", "Adestramento", "pre"),
        _skill("artes", "Artes", "pre"),
        _skill("atletismo", "Atletismo", "for"),
        _skill("atualidades", "Atualidades", "int"),
        _skill("ciencias", "Ciências", "int"),
        _skill("crime", "Crime", "agi"),
        _skill("diplomacia", "Diplomacia", "pre"),
        _skill("enganacao", "Enganação", "pre"),
        _skill("fortitude", "Fortitude", "vig"),
        _skill("furtividade", "Furtividade", "agi"),
        _skill("iniciativa", "Iniciativa", "agi"),
        _skill("intimidacao", "Intimidação", "pre"),
        _skill("intuicao", "Intuição", "pre"),
        _skill("investigacao", "Investigação", "int"),
        _skill("luta", "Luta", "for"),
        _skill("medicina", "Medicina", "int"),
        _skill("ocultismo", "Ocultismo", "int"),
        _skill("percepcao", "Percepção", "pre"),
        _skill("pilotagem", "Pilotagem", "agi"),
        _skill("pontaria", "Pontaria", "agi"),
        _skill("profissao", "Profissão", "int"),
        _skill("reflexos", "Reflexos", "agi"),
        _skill("religiao", "Religião", "pre"),
        _skill("sobrevivencia", "Sobrevivência", "int"),
        _skill("tatica", "Tática", "int"),
        _skill("tecnologia", "Tecnologia", "int"),
        _skill("vontade", "Vontade", "pre"),
    ],
    "meta_fields": [
        _meta("classe", "Classe"),
        _meta("trilha", "Trilha"),
        _meta("origem", "Origem"),
        _meta("nex", "NEX (%)", "number"),
        _meta("patente", "Patente"),
        _meta("deslocamento", "Deslocamento"),
        _meta("defesa", "Defesa", "number"),
        _meta("resistencias", "Resistências", "textarea"),
    ],
    "inventory": _inv("slots", "espaços", 2, "for", 5),
    "currencies": [_coin("dinheiro", "Dinheiro", "R$")],
    "labels": _labels("Ataques", "Rituais", "Círculo", "Habilidades e Poderes"),
}

# ---------------------------------------------------------------- D&D 5e
DND5E = {
    "roll": {"type": "d20_mod", "label": "1d20 + modificador"},
    "attribute_display": "modifier",
    "skill_mode": "proficiency",
    "attributes": [
        _attr("for", "Força", "FOR", 10, 1, 30),
        _attr("des", "Destreza", "DES", 10, 1, 30),
        _attr("con", "Constituição", "CON", 10, 1, 30),
        _attr("int", "Inteligência", "INT", 10, 1, 30),
        _attr("sab", "Sabedoria", "SAB", 10, 1, 30),
        _attr("car", "Carisma", "CAR", 10, 1, 30),
    ],
    "bars": [
        _bar("pv", "Pontos de Vida", "PV", "#c0392b", 10, short="none", long="full"),
        _bar("dv", "Dados de Vida", "DV", "#16a085", 1, short="none",
             long=_rest("half")),
        _bar("espaco1", "Espaços de Magia (1º)", "1º", "#2980b9", 0,
             short="none", long="full"),
    ],
    "skills": [
        _skill("acrobacia", "Acrobacia", "des"),
        _skill("arcanismo", "Arcanismo", "int"),
        _skill("atletismo", "Atletismo", "for"),
        _skill("atuacao", "Atuação", "car"),
        _skill("blefar", "Enganação", "car"),
        _skill("furtividade", "Furtividade", "des"),
        _skill("historia", "História", "int"),
        _skill("intimidacao", "Intimidação", "car"),
        _skill("intuicao", "Intuição", "sab"),
        _skill("investigacao", "Investigação", "int"),
        _skill("lidar_animais", "Lidar com Animais", "sab"),
        _skill("medicina", "Medicina", "sab"),
        _skill("natureza", "Natureza", "int"),
        _skill("percepcao", "Percepção", "sab"),
        _skill("persuasao", "Persuasão", "car"),
        _skill("prestidigitacao", "Prestidigitação", "des"),
        _skill("religiao", "Religião", "int"),
        _skill("sobrevivencia", "Sobrevivência", "sab"),
    ],
    "meta_fields": [
        _meta("classe", "Classe e Nível"),
        _meta("raca", "Raça"),
        _meta("antecedente", "Antecedente"),
        _meta("tendencia", "Tendência"),
        _meta("nivel", "Nível", "number"),
        _meta("prof", "Bônus de Proficiência", "number"),
        _meta("ca", "Classe de Armadura", "number"),
        _meta("deslocamento", "Deslocamento"),
        _meta("idiomas", "Idiomas e Proficiências", "textarea"),
    ],
    "inventory": _inv("weight", "kg", 0, "for", 7.5),
    "currencies": [
        _coin("pc", "Peças de Cobre", "PC"),
        _coin("pp", "Peças de Prata", "PP"),
        _coin("pe", "Peças de Electro", "PE"),
        _coin("po", "Peças de Ouro", "PO"),
        _coin("pl", "Peças de Platina", "PL"),
    ],
    "labels": _labels("Ataques", "Magias", "Nível", "Características"),
}

# ---------------------------------------------------------------- Tormenta 20
TORMENTA20 = {
    "roll": {"type": "d20_mod", "label": "1d20 + modificador + treino"},
    "attribute_display": "raw_modifier",
    "skill_mode": "training",
    "training_levels": [
        {"label": "Destreinado", "value": 0},
        {"label": "Treinado", "value": 2},
        {"label": "Veterano", "value": 4},
        {"label": "Expert", "value": 6},
    ],
    "attributes": [
        _attr("for", "Força", "FOR", 0, -5, 10),
        _attr("des", "Destreza", "DES", 0, -5, 10),
        _attr("con", "Constituição", "CON", 0, -5, 10),
        _attr("int", "Inteligência", "INT", 0, -5, 10),
        _attr("sab", "Sabedoria", "SAB", 0, -5, 10),
        _attr("car", "Carisma", "CAR", 0, -5, 10),
    ],
    "bars": [
        _bar("pv", "Pontos de Vida", "PV", "#c0392b", 16, short="none", long="full"),
        _bar("pm", "Pontos de Mana", "PM", "#2980b9", 6, short="none", long="full"),
    ],
    "skills": [
        _skill("acrobacia", "Acrobacia", "des"),
        _skill("adestramento", "Adestramento", "car"),
        _skill("atletismo", "Atletismo", "for"),
        _skill("atuacao", "Atuação", "car"),
        _skill("cavalgar", "Cavalgar", "des"),
        _skill("conhecimento", "Conhecimento", "int"),
        _skill("cura", "Cura", "sab"),
        _skill("diplomacia", "Diplomacia", "car"),
        _skill("enganacao", "Enganação", "car"),
        _skill("fortitude", "Fortitude", "con"),
        _skill("furtividade", "Furtividade", "des"),
        _skill("guerra", "Guerra", "int"),
        _skill("iniciativa", "Iniciativa", "des"),
        _skill("intimidacao", "Intimidação", "car"),
        _skill("intuicao", "Intuição", "sab"),
        _skill("investigacao", "Investigação", "int"),
        _skill("jogatina", "Jogatina", "car"),
        _skill("ladinagem", "Ladinagem", "des"),
        _skill("luta", "Luta", "for"),
        _skill("misticismo", "Misticismo", "int"),
        _skill("nobreza", "Nobreza", "int"),
        _skill("oficio", "Ofício", "int"),
        _skill("percepcao", "Percepção", "sab"),
        _skill("pilotagem", "Pilotagem", "des"),
        _skill("pontaria", "Pontaria", "des"),
        _skill("reflexos", "Reflexos", "des"),
        _skill("religiao", "Religião", "sab"),
        _skill("sobrevivencia", "Sobrevivência", "sab"),
        _skill("vontade", "Vontade", "sab"),
    ],
    "meta_fields": [
        _meta("raca", "Raça"),
        _meta("classe", "Classe"),
        _meta("nivel", "Nível", "number"),
        _meta("origem", "Origem"),
        _meta("divindade", "Divindade"),
        _meta("defesa", "Defesa", "number"),
        _meta("deslocamento", "Deslocamento"),
        _meta("tend", "Tendência"),
    ],
    "inventory": _inv("slots", "espaços", 10, "for", 2),
    "currencies": [_coin("tibar", "Tibares", "T$")],
    "labels": _labels("Ataques", "Magias", "Círculo", "Habilidades"),
}

# ---------------------------------------------------------------- Chamado de Cthulhu
CTHULHU = {
    "roll": {"type": "d100_under", "label": "1d100, role igual ou abaixo do valor"},
    "attribute_display": "percent",
    "skill_mode": "percent",
    "attributes": [
        _attr("for", "Força", "FOR", 50, 0, 99),
        _attr("con", "Constituição", "CON", 50, 0, 99),
        _attr("tam", "Tamanho", "TAM", 50, 0, 99),
        _attr("des", "Destreza", "DES", 50, 0, 99),
        _attr("apa", "Aparência", "APA", 50, 0, 99),
        _attr("int", "Inteligência", "INT", 50, 0, 99),
        _attr("pod", "Poder", "POD", 50, 0, 99),
        _attr("edu", "Educação", "EDU", 50, 0, 99),
        _attr("sorte", "Sorte", "SOR", 50, 0, 99),
    ],
    "bars": [
        _bar("pv", "Pontos de Vida", "PV", "#c0392b", 10, short=_rest("amount", 1),
             long="full"),
        _bar("san", "Sanidade", "SAN", "#8e44ad", 50, short="none", long="none"),
        _bar("pm", "Pontos de Magia", "PM", "#2980b9", 10, short="none", long="full"),
    ],
    "skills": [
        _skill("antropologia", "Antropologia", "int", 1),
        _skill("arqueologia", "Arqueologia", "int", 1),
        _skill("armas_fogo_pistola", "Armas de Fogo (Pistola)", "des", 20),
        _skill("armas_fogo_rifle", "Armas de Fogo (Rifle)", "des", 25),
        _skill("arremessar", "Arremessar", "des", 20),
        _skill("artes_oficios", "Artes e Ofícios", "des", 5),
        _skill("avaliacao", "Avaliação", "int", 5),
        _skill("briga", "Lutar (Briga)", "for", 25),
        _skill("cavalgar", "Cavalgar", "des", 5),
        _skill("charme", "Charme", "apa", 15),
        _skill("chaveiro", "Chaveiro", "des", 1),
        _skill("ciencia", "Ciência", "int", 1),
        _skill("computador", "Usar Computadores", "int", 5),
        _skill("consertos_eletricos", "Consertos Elétricos", "int", 10),
        _skill("consertos_mecanicos", "Consertos Mecânicos", "int", 10),
        _skill("contabilidade", "Contabilidade", "int", 5),
        _skill("direcao", "Dirigir Automóveis", "des", 20),
        _skill("disfarce", "Disfarce", "apa", 5),
        _skill("eletronica", "Eletrônica", "int", 1),
        _skill("encontrar", "Encontrar (Localizar)", "int", 25),
        _skill("escalar", "Escalar", "for", 20),
        _skill("escutar", "Escutar", "int", 20),
        _skill("esquivar", "Esquivar", "des", 0),
        _skill("furtividade", "Furtividade", "des", 20),
        _skill("historia", "História", "int", 5),
        _skill("intimidacao", "Intimidação", "pod", 15),
        _skill("labia", "Lábia", "apa", 5),
        _skill("lingua_nativa", "Língua Nativa", "edu", 0),
        _skill("lingua_outra", "Outra Língua", "int", 1),
        _skill("medicina", "Medicina", "int", 1),
        _skill("mitos", "Mitos de Cthulhu", "int", 0),
        _skill("natacao", "Natação", "for", 20),
        _skill("navegacao", "Navegação", "int", 10),
        _skill("ocultismo", "Ocultismo", "int", 5),
        _skill("persuasao", "Persuasão", "int", 10),
        _skill("pilotagem", "Pilotagem", "des", 1),
        _skill("primeiros_socorros", "Primeiros Socorros", "des", 30),
        _skill("psicanalise", "Psicanálise", "edu", 1),
        _skill("psicologia", "Psicologia", "int", 10),
        _skill("rastrear", "Rastrear", "int", 10),
        _skill("saltar", "Saltar", "for", 20),
        _skill("sobrevivencia", "Sobrevivência", "int", 10),
        _skill("usar_bibliotecas", "Usar Bibliotecas", "edu", 20),
    ],
    "meta_fields": [
        _meta("ocupacao", "Ocupação"),
        _meta("idade", "Idade", "number"),
        _meta("residencia", "Residência"),
        _meta("local_nascimento", "Local de Nascimento"),
        _meta("movimento", "Movimento", "number"),
        _meta("dano_bonus", "Dano Bônus"),
        _meta("build", "Corpo (Build)"),
        _meta("patrimonio", "Nível de Vida / Patrimônio"),
    ],
    "inventory": _inv("none"),
    "currencies": [_coin("dinheiro", "Dinheiro", "$")],
    "labels": _labels("Armas e Ataques", "Feitiços", "Nível", "Talentos"),
}

# ---------------------------------------------------------------- Vampiro: A Máscara
VAMPIRO = {
    "roll": {"type": "pool_d10", "label": "Some atributo + habilidade em d10 (sucesso em 6+)", "success_on": 6},
    "attribute_display": "dots",
    "skill_mode": "dots",
    "attributes": [
        _attr("forca", "Força", "FOR", 1, 0, 5),
        _attr("destreza", "Destreza", "DES", 1, 0, 5),
        _attr("vigor", "Vigor", "VIG", 1, 0, 5),
        _attr("carisma", "Carisma", "CAR", 1, 0, 5),
        _attr("manipulacao", "Manipulação", "MAN", 1, 0, 5),
        _attr("compostura", "Compostura", "CMP", 1, 0, 5),
        _attr("inteligencia", "Inteligência", "INT", 1, 0, 5),
        _attr("raciocinio", "Raciocínio", "RAC", 1, 0, 5),
        _attr("determinacao", "Determinação", "DET", 1, 0, 5),
    ],
    "bars": [
        _bar("vitalidade", "Vitalidade", "VIT", "#c0392b", 5, short="none", long="full"),
        _bar("vontade", "Força de Vontade", "FV", "#f39c12", 5, short="none", long="full"),
        _bar("vitae", "Vitae / Sangue", "SNG", "#7b1e1e", 10, short="none", long="none"),
        _bar("humanidade", "Humanidade", "HUM", "#bdc3c7", 10, short="none", long="none"),
    ],
    "skills": [
        _skill("prontidao", "Prontidão", "raciocinio"),
        _skill("esportes", "Esportes", "destreza"),
        _skill("briga", "Briga", "forca"),
        _skill("empatia", "Empatia", "raciocinio"),
        _skill("expressao", "Expressão", "carisma"),
        _skill("intimidacao", "Intimidação", "carisma"),
        _skill("labia", "Lábia", "manipulacao"),
        _skill("lideranca", "Liderança", "carisma"),
        _skill("manha", "Manha", "raciocinio"),
        _skill("perspicacia", "Perspicácia", "raciocinio"),
        _skill("armas_brancas", "Armas Brancas", "destreza"),
        _skill("armas_fogo", "Armas de Fogo", "destreza"),
        _skill("conducao", "Condução", "destreza"),
        _skill("etiqueta", "Etiqueta", "carisma"),
        _skill("furtividade", "Furtividade", "destreza"),
        _skill("oficios", "Ofícios", "destreza"),
        _skill("performance", "Performance", "carisma"),
        _skill("seguranca", "Segurança", "destreza"),
        _skill("sobrevivencia", "Sobrevivência", "raciocinio"),
        _skill("trato_animais", "Trato com Animais", "manipulacao"),
        _skill("academicos", "Acadêmicos", "inteligencia"),
        _skill("ciencias", "Ciências", "inteligencia"),
        _skill("computador", "Computador", "inteligencia"),
        _skill("direito", "Direito", "inteligencia"),
        _skill("financas", "Finanças", "inteligencia"),
        _skill("investigacao", "Investigação", "inteligencia"),
        _skill("medicina", "Medicina", "inteligencia"),
        _skill("ocultismo", "Ocultismo", "inteligencia"),
        _skill("politica", "Política", "inteligencia"),
        _skill("tecnologia", "Tecnologia", "inteligencia"),
    ],
    "meta_fields": [
        _meta("cla", "Clã"),
        _meta("geracao", "Geração", "number"),
        _meta("senda", "Senda / Trilha"),
        _meta("predador", "Tipo de Predador"),
        _meta("sire", "Senhor (Sire)"),
        _meta("ambicao", "Ambição"),
        _meta("desejo", "Desejo"),
        _meta("disciplinas", "Disciplinas", "textarea"),
        _meta("toques", "Toques de Consciência", "textarea"),
    ],
    "inventory": _inv("none"),
    "currencies": [],
    "labels": _labels("Ataques", "Disciplinas", "Nível", "Vantagens e Defeitos"),
}

# ---------------------------------------------------------------- Genérico
GENERICO = {
    "roll": {"type": "d20_mod", "label": "1d20 + modificador"},
    "attribute_display": "number",
    "skill_mode": "bonus",
    "attributes": [
        _attr("corpo", "Corpo", "COR", 2, 0, 10),
        _attr("mente", "Mente", "MEN", 2, 0, 10),
        _attr("alma", "Alma", "ALM", 2, 0, 10),
    ],
    "bars": [
        _bar("pv", "Pontos de Vida", "PV", "#c0392b", 10, short=_rest("half"), long="full",
             max_formula="10 + COR * 5"),
        _bar("recurso", "Recurso", "REC", "#2980b9", 5, short="none", long="full",
             max_formula="ALM * 2"),
    ],
    "skills": [
        _skill("combate", "Combate", "corpo"),
        _skill("atletismo", "Atletismo", "corpo"),
        _skill("conhecimento", "Conhecimento", "mente"),
        _skill("percepcao", "Percepção", "mente"),
        _skill("social", "Social", "alma"),
        _skill("vontade", "Vontade", "alma"),
    ],
    "meta_fields": [
        _meta("conceito", "Conceito"),
        _meta("nivel", "Nível", "number"),
        _meta("defesa", "Defesa", "number"),
    ],
    "inventory": _inv("weight", "kg", 0, "corpo", 10),
    "currencies": [_coin("moeda", "Moedas", "$")],
    "labels": _labels(),
}


PRESETS = [
    {
        "name": "Ordem Paranormal",
        "slug": "ordem-paranormal",
        "description": "Agentes da Ordem contra o Outro Lado. Atributos de 0 a 5, rolagem de "
                       "múltiplos d20 pegando o maior, com PV/PE/Sanidade e NEX.",
        "data": ORDEM,
    },
    {
        "name": "D&D 5ª Edição",
        "slug": "dnd-5e",
        "description": "Seis atributos com modificador calculado, perícias por proficiência "
                       "e 1d20 + modificador.",
        "data": DND5E,
    },
    {
        "name": "Tormenta 20",
        "slug": "tormenta-20",
        "description": "Arton em d20. Atributos já em modificador, perícias com graus de "
                       "treinamento, PV e PM.",
        "data": TORMENTA20,
    },
    {
        "name": "Chamado de Cthulhu",
        "slug": "chamado-de-cthulhu",
        "description": "Investigadores do Mythos. Sistema percentual (d100), Sanidade e "
                       "perícias com valor base.",
        "data": CTHULHU,
    },
    {
        "name": "Vampiro: A Máscara",
        "slug": "vampiro-a-mascara",
        "description": "Mundo das Trevas. Nove atributos em pontos (1 a 5), parada de dados "
                       "d10 com sucesso em 6+, Fome e Humanidade.",
        "data": VAMPIRO,
    },
    {
        "name": "Genérico / Crie o seu",
        "slug": "generico",
        "description": "Base mínima para você montar um sistema do zero: três atributos, "
                       "duas barras com máximo calculado por fórmula e seis perícias.",
        "data": GENERICO,
    },
]

# Iniciativa de cada sistema (ver app/initiative.py).
_INITIATIVE = {
    "ordem-paranormal": {"source": "skill", "key": "iniciativa", "roll": True},
    "dnd-5e": {"source": "attribute", "key": "des", "roll": True},
    "tormenta-20": {"source": "skill", "key": "iniciativa", "roll": True},
    "chamado-de-cthulhu": {"source": "attribute", "key": "des", "roll": False},
    "vampiro-a-mascara": {"source": "formula", "formula": "DES + RAC", "roll": False},
    "generico": {"source": "attribute", "key": "corpo", "roll": True},
}
for _preset in PRESETS:
    _preset["data"]["initiative"] = dict(_INITIATIVE[_preset["slug"]])


def sync_presets(db, GameSystem):
    """Cria (ou atualiza) os sistemas pré-definidos no banco."""
    changed = False
    for preset in PRESETS:
        system = GameSystem.query.filter_by(slug=preset["slug"], is_preset=True).first()
        if system is None:
            system = GameSystem(
                name=preset["name"],
                slug=preset["slug"],
                description=preset["description"],
                is_preset=True,
                owner_id=None,
                data=preset["data"],
            )
            db.session.add(system)
            changed = True
        else:
            system.name = preset["name"]
            system.description = preset["description"]
            system.data = preset["data"]
            changed = True
    if changed:
        db.session.commit()
