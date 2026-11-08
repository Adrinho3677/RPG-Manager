# -*- coding: utf-8 -*-
"""Limiar: regras de criação de personagem e conferência da ficha.

O sistema Limiar é um preset como os outros (ver app/presets.py), mas a criação
tem regras que um modelo de ficha genérico não sabe conferir: pontos de
atributo, perícias do passado e do arquétipo, orçamento de Bênçãos e Marcas,
afinidades arcanas e os dons do Canalizador. Este módulo guarda essas regras,
confere uma escolha de criação (`check_creation`), monta a ficha a partir dela
(`build_data`) e confere uma ficha já em jogo (`check_sheet`).

Duas versões das regras convivem: a 0.23 (a do playtest) e a 0.24, que
acrescenta a afinidade de nascença, o combustível e o passado Quebra-Pacto.
"""
import re

from app import dice
from app.utils import to_int

SLUG = "limiar"
VERSIONS = ("0.23", "0.24")
DEFAULT_VERSION = "0.23"

ATTRIBUTES = [
    {"key": "corpo", "name": "Corpo", "abbr": "COR"},
    {"key": "mente", "name": "Mente", "abbr": "MEN"},
    {"key": "alma", "name": "Alma", "abbr": "ALM"},
    {"key": "poder", "name": "Poder", "abbr": "POD"},
]

SKILLS = [
    ("atletismo", "Atletismo", "corpo"),
    ("acrobacia", "Acrobacia", "corpo"),
    ("fortitude", "Fortitude", "corpo"),
    ("furtividade", "Furtividade", "corpo"),
    ("luta", "Luta", "corpo"),
    ("pontaria", "Pontaria", "corpo"),
    ("investigacao", "Investigação", "mente"),
    ("percepcao", "Percepção", "mente"),
    ("historia_antiga", "História Antiga", "mente"),
    ("medicina", "Medicina", "mente"),
    ("sobrevivencia", "Sobrevivência", "mente"),
    ("oficios", "Ofícios", "mente"),
    ("vontade", "Vontade", "alma"),
    ("diplomacia", "Diplomacia", "alma"),
    ("intuicao", "Intuição", "alma"),
    ("intimidacao", "Intimidação", "alma"),
    ("enganacao", "Enganação", "alma"),
    ("canalizacao", "Canalização", "poder"),
    ("reliquias", "Relíquias", "poder"),
    ("ritualistica", "Ritualística", "poder"),
]
SKILL_NAMES = {key: name for key, name, _ in SKILLS}

TRAINING = [
    {"label": "Destreinado", "value": 0},
    {"label": "Treinado", "value": 5},
    {"label": "Avançado", "value": 10},
    {"label": "Mestre", "value": 15},
]

TERRAS = [
    ("cidades_livres", "Cidades Livres", "Pede tudo por escrito e confere o troco."),
    ("dominios", "Domínios", "Fica de costas para a parede e fala baixo perto de uniformes."),
    ("somara", "Sômara", "Lembra o sobrenome de todo mundo, e o que a família deles fez."),
    ("anel", "Anel de Sal", "Faz tudo em círculos: acender velas, dar nós, dizer adeus."),
    ("altas_terras", "Altas Terras", "Não aceita presente sem dar outro em troca."),
    ("sakura", "Sakura", "Nunca diz \"não\" diretamente, e ouve quando os outros não dizem."),
    ("mil_velas", "Mil Velas", "Olha o céu antes de responder e não assobia em lugar fechado."),
    ("mar_de_vidro", "Mar de Vidro", "Divide a água antes da comida, e não desperdiça nenhuma das duas."),
]


def _passado(key, name, skills, ability, text, since="0.23"):
    return {"key": key, "name": name, "skills": skills, "ability": ability, "text": text,
            "since": since}


PASSADOS = [
    _passado("arqueologo", "Arqueólogo", ["historia_antiga", "investigacao"], "Datação",
             "Ao examinar uma ruína ou objeto antigo, sabe sem teste a sua época e a qual "
             "entidade está ligado."),
    _passado("cacador", "Caçador de Relíquias", ["reliquias", "furtividade"], "Olho Treinado",
             "+5 na primeira ativação de cada relíquia desconhecida, e sabe estimar o valor de "
             "qualquer relíquia que segure."),
    _passado("membro_ordem", "Membro de Ordem", ["ritualistica", "vontade"], "Irmandade",
             "Escolha uma facção. Tem contatos nela e pode pedir abrigo, informação ou ajuda "
             "simples."),
    _passado("mercenario", "Mercenário", ["luta", "intimidacao"], "Embalo (2 PI)",
             "Ao derrubar um inimigo, faz um ataque extra contra outro alvo ao alcance."),
    _passado("erudito", "Erudito", ["historia_antiga", "medicina"], "Razão Fria",
             "Pode usar Mente no lugar de Alma nos testes para reduzir a Dissonância de um "
             "aliado ou tirá-lo do estado Ficando Louco."),
    _passado("sobrevivente", "Sobrevivente", ["sobrevivencia", "fortitude"], "Teimosia",
             "No estado Morrendo, tem 4 rodadas em vez de 3."),
    _passado("escavador", "Escavador", ["atletismo", "oficios"], "Instinto de Túnel",
             "Percebe sem teste quando uma estrutura está prestes a desabar, e recebe +5 em "
             "Percepção em ambientes subterrâneos."),
    _passado("desertor", "Desertor", ["luta", "enganacao"], "Conhece o Inimigo",
             "+5 em testes para prever, enganar ou se infiltrar entre forças da Potestas "
             "Dominus. A Potestas não esquece."),
    _passado("peregrino", "Peregrino", ["sobrevivencia", "intuicao"], "Caminhos Antigos",
             "Nunca se perde em viagem, e seus descansos longos recuperam +1d6 PI."),
    _passado("curandeiro", "Curandeiro", ["medicina", "intuicao"], "Mãos Firmes",
             "A DT para estabilizar alguém cai 5, e quem você trata em um descanso curto "
             "recupera +1d6 PV."),
    _passado("contrabandista", "Contrabandista", ["furtividade", "enganacao"], "Fundo Falso",
             "Carrega até dois itens pequenos que ninguém encontra sem Investigação (DT 25), e "
             "nunca paga o Quinto sobre eles."),
    _passado("cartografo", "Cartógrafo", ["sobrevivencia", "investigacao"], "Mapa Mental",
             "Nunca se perde em um lugar por onde já passou, e o mapa que desenha numa descida "
             "vale como Mapa de Galeria na próxima."),
    _passado("acolito", "Acólito", ["ritualistica", "diplomacia"], "Portas do Templo",
             "Escolha a Aioneco ou o Coração Imanente. Os santuários dela lhe dão abrigo e "
             "reduzem 1d6 de Dissonância uma vez por descanso longo."),
    _passado("nobre_caido", "Nobre Caído", ["diplomacia", "historia_antiga"], "Nome Antigo",
             "+5 em Diplomacia com autoridades e pessoas ricas."),
    _passado("artifice", "Artífice", ["oficios", "reliquias"], "Olho de Oficina",
             "As modificações de equipamento custam 25% menos, e pode aplicá-las sozinho "
             "durante um interlúdio."),
    _passado("marinheiro", "Marinheiro", ["atletismo", "sobrevivencia"], "Pernas de Mar",
             "Não sofre penalidade por terreno instável, e prevê o clima das próximas 24 horas "
             "sem teste."),
    _passado("mercador", "Mercador", ["diplomacia", "intuicao"], "Olho no Preço",
             "Compra 10% mais barato e vende 10% mais caro, e avalia qualquer mercadoria sem "
             "teste."),
    _passado("cortesao", "Cortesão", ["enganacao", "intuicao"], "Salão Conhecido",
             "Em qualquer corte, sabe sem teste quem manda de verdade, e recebe +5 em Intuição "
             "contra nobres."),
    _passado("campones", "Camponês", ["fortitude", "sobrevivencia"], "Gente Como a Gente",
             "Em aldeias e bairros pobres, encontra abrigo e comida de graça, e as pessoas "
             "contam o que nunca contariam a um estrangeiro."),
    _passado("bandoleiro", "Bandoleiro", ["pontaria", "furtividade"], "Conhece a Estrada",
             "Não pode ser surpreendido em viagem, e sabe onde há esconderijos e receptadores "
             "em qualquer região."),
    _passado("artista", "Artista", ["diplomacia", "enganacao"], "Público Certo",
             "Uma apresentação paga 2d6 × 5 dr por dia e dá +5 no próximo teste de Diplomacia "
             "ou Enganação com quem assistiu."),
    _passado("quebra_pacto", "Quebra-Pacto", ["investigacao", "vontade"], "Mão Fria",
             "Sabe, sem teste, se alguém tem um pacto com um ser sem sombra, e recebe +5 em "
             "Vontade contra eles.", since="0.24"),
]


def _arquetipo(key, name, pv, pv_lv, pi, pi_lv, skills, kit, n1, n1_text):
    return {"key": key, "name": name, "pv_base": pv, "pv_nivel": pv_lv, "pi_base": pi,
            "pi_nivel": pi_lv, "skills": skills, "kit": kit, "n1": n1, "n1_text": n1_text}


ARQUETIPOS = [
    _arquetipo("vanguarda", "Vanguarda", 15, 5, 2, 2, ["luta", "fortitude"],
               {"weapon": "media", "armor": "media", "shield": True,
                "items": []},
               "Escudo Vivo (2 PI)",
               "Recebe o dano de um ataque destinado a um aliado adjacente."),
    _arquetipo("decifrador", "Decifrador", 10, 3, 3, 2, ["investigacao", "historia_antiga"],
               {"weapon": "leve", "armor": "leve", "shield": False,
                "items": ["kit_exploracao"]},
               "Leitura do Mundo (2 PI)",
               "Faz uma pergunta ao mestre sobre o lugar ou a criatura, e o mestre responde "
               "com a verdade."),
    _arquetipo("ancora", "Âncora", 12, 4, 3, 2, ["vontade", "intuicao"],
               {"weapon": "leve", "armor": "leve", "shield": False,
                "items": ["kit_medico"]},
               "Elo",
               "+5 nos testes de Alma para reduzir a Dissonância de aliados ou tirá-los do "
               "estado Ficando Louco."),
    _arquetipo("canalizador", "Canalizador", 8, 3, 4, 3, ["canalizacao", "reliquias"],
               {"weapon": "leve", "armor": "", "shield": False,
                "items": ["kit_exploracao", "bandagens"]},
               "Fonte Interior",
               "Começa com dois dons menores, e o primeiro dom que usa em cada cena custa 1 PI "
               "a menos."),
]

KIT_ITEMS = {
    "kit_exploracao": {"name": "Kit de exploração", "value": 15,
                       "desc": "Corda, lanterna, pederneira, ferramentas."},
    "kit_medico": {"name": "Kit médico", "value": 20,
                   "desc": "Sem ele, a DT para estabilizar alguém sobe 5."},
    "bandagens": {"name": "Bandagens (3)", "value": 5, "desc": "Tratam Sangrando sem teste."},
}


def _weapon(key, name, kind, price, props, ranged=False):
    return {"key": key, "name": name, "type": kind, "price": price, "props": props,
            "ranged": ranged}


WEAPONS = {
    "leve": {"label": "Arma leve", "damage": "1d6", "items": [
        _weapon("punhal", "Punhal", "Perfuração", 10, "Arremesso, Oculta. +1d6 contra alvo surpreso."),
        _weapon("faca_caca", "Faca de caça", "Corte", 8, "Oculta. +2 em Sobrevivência para caçar e abrigar."),
        _weapon("porrete", "Porrete", "Impacto", 3, "Pode derrubar a 0 PV sem matar."),
        _weapon("machadinha", "Machadinha", "Corte", 10, "Arremesso. Corta madeira e corda."),
        _weapon("espada_curta", "Espada curta", "Perfuração", 15, "+1 em Contra-ataque. Sem penalidade em lugares estreitos."),
        _weapon("tessen", "Tessen", "Corte", 30, "Oculta. Ao Defender-se, +3 de Defesa, e não +2."),
        _weapon("funda", "Funda", "Impacto", 2, "Arremesso. Usa qualquer pedra como munição.", True),
        _weapon("dardos", "Dardos (3)", "Perfuração", 6, "Arremesso. O dardo pode ser recuperado.", True),
        _weapon("picareta", "Picareta", "Perfuração", 5, "Dano dobrado contra pedra e madeira."),
    ]},
    "media": {"label": "Arma média", "damage": "1d8", "items": [
        _weapon("espada_longa", "Espada longa", "Corte", 25, "Com as duas mãos, +2 de dano."),
        _weapon("rapieira", "Rapieira", "Perfuração", 40, "+2 em Contra-ataque."),
        _weapon("sabre", "Sabre", "Corte", 25, "Sem penalidade em terreno instável."),
        _weapon("cimitarra", "Cimitarra", "Corte", 30, "+2 de dano se você se moveu antes de atacar."),
        _weapon("katana", "Katana", "Corte", 80, "Ignora 1 de RD. Um 20 natural deixa o alvo Sangrando."),
        _weapon("machado_batalha", "Machado de batalha", "Corte", 25, "O alvo não soma o escudo à Defesa."),
        _weapon("maca", "Maça", "Impacto", 20, "Ignora 2 de RD."),
        _weapon("lanca", "Lança", "Perfuração", 20, "Haste, Arremesso. +1d6 em um ataque Preparado."),
        _weapon("arco_curto", "Arco curto", "Perfuração", 25, "Distância, Duas Mãos.", True),
        _weapon("arco_longo", "Arco longo", "Perfuração", 40, "Distância, Duas Mãos. Alcance de 60 metros.", True),
        _weapon("besta_leve", "Besta leve", "Perfuração", 30, "Distância, Duas Mãos. Ignora 1 de RD.", True),
        _weapon("pistola_roda", "Pistola de roda", "Perfuração", 150, "Alcance de 10 metros. Recarga, Pólvora, Oculta.", True),
    ]},
}

ARMORS = {
    "leve": {"label": "Armadura leve", "defense": 2, "items": [
        {"key": "gibao", "name": "Gibão acolchoado", "resist": "Impacto 1", "weak": "Fogo 2"},
        {"key": "couro", "name": "Couro", "resist": "Corte 1", "weak": "Perfuração 1"},
        {"key": "seda_dupla", "name": "Seda dupla", "resist": "Perfuração 2", "weak": "Corte 1, Fogo 1"},
    ]},
    "media": {"label": "Armadura média", "defense": 4, "penalty": "−5 em Furtividade", "items": [
        {"key": "couro_fervido", "name": "Couro fervido", "resist": "Corte 1, Impacto 1", "weak": "Perfuração 1"},
        {"key": "cota_malha", "name": "Cota de malha", "resist": "Corte 2", "weak": "Perfuração 1, Impacto 1"},
        {"key": "lamelas", "name": "Lamelas", "resist": "Corte 2, Perfuração 1", "weak": "Impacto 2"},
    ]},
}

SHIELDS = [
    {"key": "broquel", "name": "Broquel", "effect": "Bloqueia ataques à distância. +1 em Contra-ataque."},
    {"key": "escudo_madeira", "name": "Escudo de madeira", "effect": "Bloqueia ataques à distância. Fraqueza a Fogo 1."},
    {"key": "escudo_torre", "name": "Escudo de torre", "effect": "Dá cobertura parcial. −5 em Acrobacia."},
]


def _b(key, name, cost, entity, effect, needs=""):
    return {"key": key, "name": name, "cost": cost, "entity": entity, "effect": effect,
            "needs": needs}


BENCAOS = [
    _b("resistente", "Resistente", 2, "Corpo", "+2 em testes de Fortitude"),
    _b("passos_leves", "Passos Leves", 2, "Corpo", "+2 em Furtividade"),
    _b("braco_forte", "Braço Forte", 2, "Corpo", "+2 em Atletismo"),
    _b("olhos_gato", "Olhos de Gato", 2, "Corpo", "Enxerga na penumbra como se houvesse luz fraca"),
    _b("sangue_grosso", "Sangue Grosso", 3, "Corpo", "Sangrando causa só 1 PV por turno"),
    _b("olhar_atento", "Olhar Atento", 2, "Mente", "+2 em Percepção"),
    _b("memoria_antiga", "Memória Antiga", 3, "Mente", "Uma vez por sessão, lembra um fato útil sobre o mundo antigo"),
    _b("poliglota", "Poliglota", 2, "Mente", "Lê e fala mais três línguas vivas; +2 em História Antiga para línguas mortas"),
    _b("senso_direcao", "Senso de Direção", 2, "Mente", "+2 em Sobrevivência"),
    _b("maos_oficina", "Mãos de Oficina", 2, "Mente", "+2 em Ofícios"),
    _b("vontade_ferro", "Vontade de Ferro", 3, "Alma", "+2 em Vontade contra influência sobrenatural"),
    _b("carismatico", "Carismático", 2, "Alma", "+2 em Diplomacia"),
    _b("rosto_confiavel", "Rosto Confiável", 2, "Alma", "+2 em Enganação"),
    _b("coracao_calmo", "Coração Calmo", 3, "Alma", "Reduz em 1 toda Dissonância que ganhar por exposição"),
    _b("laco_antigo", "Laço Antigo", 2, "Alma", "Tem um contato de confiança em uma facção à sua escolha"),
    _b("sensivel", "Sensível às Energias", 2, "Poder", "Percebe relíquias e fontes de poder próximas"),
    _b("canal_estavel", "Canal Estável", 3, "Poder", "+2 em Canalização"),
    _b("dom_aprendido", "Dom Aprendido", 3, "Poder", "Aprende um dom menor", needs="dom"),
    _b("mao_reliquia", "Mão de Relíquia", 3, "Poder", "+2 em Relíquias"),
    _b("sintonia_ampla", "Sintonia Ampla", 3, "Poder", "Pode se sintonizar com uma relíquia a mais"),
]

MARCAS = [
    _b("ferida_antiga", "Ferida Antiga", 2, "Corpo", "Esforço extremo causa dor que exige teste de Fortitude"),
    _b("desajeitado", "Desajeitado", 1, "Corpo", "−2 em Acrobacia"),
    _b("pulmao_fraco", "Pulmão Fraco", 1, "Corpo", "−2 em Fortitude para aguentar poeira, gás ou falta de ar"),
    _b("medo_altura", "Medo de Altura", 2, "Corpo", "Vontade (DT 15) para agir perto de um abismo"),
    _b("obsessivo", "Obsessivo", 2, "Mente", "Difícil abandonar um mistério, mesmo em perigo"),
    _b("distraido", "Distraído", 1, "Mente", "−2 em Percepção"),
    _b("pesadelos", "Pesadelos", 2, "Mente", "Vontade (DT 15) ou o descanso longo recupera metade do PI"),
    _b("curioso", "Curioso Demais", 1, "Mente", "Precisa tocar, abrir ou ler. Vontade (DT 15) para resistir."),
    _b("assombrado", "Assombrado", 3, "Alma", "Uma presença do passado o acompanha"),
    _b("desconfiado", "Desconfiado", 1, "Alma", "−2 em Diplomacia com estranhos"),
    _b("divida", "Dívida", 2, "Alma", "Deve dinheiro ou um favor a alguém que vai cobrar"),
    _b("procurado", "Procurado", 3, "Alma", "Uma facção ou cidade quer você. Comece com −1 de reputação nela."),
    _b("voto", "Voto", 1, "Alma", "Jurou nunca fazer algo específico. Quebrar o voto custa 1d6 de Dissonância."),
    _b("energia_instavel", "Energia Instável", 2, "Poder", "Falhas com Poder causam efeitos colaterais"),
    _b("atrai_reliquias", "Atrai Relíquias", 2, "Poder", "Objetos antigos reagem à sua presença"),
    _b("queima_rapido", "Queima Rápido", 1, "Poder", "O Ímpeto recuperado em descanso curto cai pela metade"),
]

BENCAO_BUDGET = 4
SEM_AFINIDADE_BONUS = 3   # v0.24: quem nasce sem afinidade
MARCA_POINTS_MAX = 6
MARCAS_MAX = 3
BENCAO_SPEND_MAX = 10

ESCOLAS = [
    {"key": "carne", "name": "Carne", "entity": "Corpo", "opposite": "tempestade",
     "fuel": "Seiva-sangue", "price": 6},
    {"key": "pedra", "name": "Pedra", "entity": "Corpo", "opposite": "forca",
     "fuel": "Giz de prata", "price": 4},
    {"key": "veu", "name": "Véu", "entity": "Mente", "opposite": "vigia",
     "fuel": "Cinza de seda", "price": 8},
    {"key": "vigia", "name": "Vigia", "entity": "Mente", "opposite": "veu",
     "fuel": "Vidro negro", "price": 6},
    {"key": "laco", "name": "Laço", "entity": "Alma", "opposite": "eco",
     "fuel": "Sal do Anel", "price": 2},
    {"key": "eco", "name": "Eco", "entity": "Alma", "opposite": "laco",
     "fuel": "Cinza de sebo negro", "price": 5},
    {"key": "tempestade", "name": "Tempestade", "entity": "Poder", "opposite": "carne",
     "fuel": "Pólvora fina", "price": 10},
    {"key": "forca", "name": "Força", "entity": "Poder", "opposite": "pedra",
     "fuel": "Âmbar de baleia", "price": 8},
]
ESCOLA_BY_KEY = {e["key"]: e for e in ESCOLAS}


def _dom(key, name, school, reach, text, since="0.23"):
    return {"key": key, "name": name, "school": school, "reach": reach, "text": text,
            "since": since}


# Dons menores (custo 1 PI, DT 15). Os marcados since=0.24 são os novos do Grimório.
DONS_MENORES = [
    _dom("revigorar", "Revigorar", "carne", "toque", "O alvo recupera 1d8 + Corpo PV."),
    _dom("forca_bruta", "Força Bruta", "carne", "toque", "O alvo recebe +5 no próximo teste de Atletismo ou Fortitude."),
    _dom("passo_veloz", "Passo Veloz", "carne", "você", "Ganha um movimento extra neste turno."),
    _dom("garras", "Garras", "carne", "você", "Até o fim da cena, seus ataques desarmados causam 1d8 de Corte.", "0.24"),
    _dom("pele_ferro", "Pele de Ferro", "pedra", "toque", "O alvo recebe +3 de Defesa por 3 rodadas."),
    _dom("chao_firme", "Chão Firme", "pedra", "você", "Até o fim da cena, ignora terreno difícil e não pode ser derrubado nem empurrado.", "0.24"),
    _dom("moldar_pedra", "Moldar Pedra", "pedra", "toque", "Molda até um metro cúbico de pedra ou terra, como se fosse barro. Leva um minuto.", "0.24"),
    _dom("ruido", "Ruído", "veu", "curto", "O alvo sofre −5 no próximo teste."),
    _dom("miragem", "Miragem", "veu", "médio", "Cria uma imagem imóvel do tamanho de uma pessoa, sem som. Investigação (DT 15) percebe.", "0.24"),
    _dom("disfarce", "Disfarce", "veu", "você", "Por uma hora, parece outra pessoa, mas não alguém específico.", "0.24"),
    _dom("sentir_intencao", "Sentir Intenção", "vigia", "curto", "Sabe se a criatura está mentindo e qual a sua próxima intenção; +5 no próximo teste contra ela."),
    _dom("lembranca_perfeita", "Lembrança Perfeita", "vigia", "você", "+5 no próximo teste de História Antiga ou Investigação."),
    _dom("elo_mental", "Elo Mental", "vigia", "aliados próximos", "Até o fim da cena, vocês se comunicam por pensamento."),
    _dom("ver_rastro", "Ver o Rastro", "vigia", "você", "Por uma cena, vê pegadas, marcas e restos de calor dos últimos três dias.", "0.24"),
    _dom("voz_comando", "Voz de Comando", "laco", "curto", "Vontade (DT 15); na falha, obedece a um comando de uma palavra no próximo turno."),
    _dom("encorajar", "Encorajar", "laco", "curto", "Um aliado recebe +3 no próximo teste."),
    _dom("acalmar", "Acalmar", "laco", "toque", "O alvo reduz 1d4 de Dissonância. Uma vez por cena por alvo."),
    _dom("juramento_selado", "Juramento Selado", "laco", "toque", "Duas pessoas fazem uma promessa; se uma quebrar, as duas sabem na hora.", "0.24"),
    _dom("sentir_almas", "Sentir Almas", "eco", "você", "Percebe todos os seres vivos e aberrações a até 30 metros."),
    _dom("afastar_espiritos", "Afastar Espíritos", "eco", "curto", "Até o fim da cena, ecos e presenças de mortos não se aproximam.", "0.24"),
    _dom("descarga", "Descarga", "tempestade", "ataque, médio", "Causa 2d6 de dano de energia."),
    _dom("luz_fria", "Luz Fria", "tempestade", "curto", "Luz sem chama até o fim da cena; quem olhar faz Fortitude (DT 15) ou −5 no próximo teste."),
    _dom("chama", "Chama", "tempestade", "ataque, curto", "Precisa de algo que queime ao alcance. 2d6 de Fogo, e o alvo pega fogo.", "0.24"),
    _dom("mover", "Mover", "forca", "curto", "Empurra ou puxa um objeto ou criatura em até 5 metros (Fortitude DT 15 resiste)."),
    _dom("escudo_energia", "Escudo de Energia", "forca", "você", "Reduz em 5 o dano do próximo ataque que receber nesta rodada."),
    _dom("salto_vento", "Salto de Vento", "forca", "você", "Salta até 10 metros em qualquer direção, sem teste, e cai sem dano.", "0.24"),
]
DOM_BY_KEY = {d["key"]: d for d in DONS_MENORES}

# XP total para cada nível (índice = nível).
XP_TABLE = [None, 0, 10, 20, 30, 40, 55, 70, 85, 100, 115, 135, 155, 175, 195, 215, 240,
            265, 290, 315, 340]
SKILL_GRADE_LEVELS = (2, 5, 10, 13, 19)
ATTRIBUTE_LEVELS = (8, 16)

PASSADO_BY_KEY = {p["key"]: p for p in PASSADOS}
ARQUETIPO_BY_KEY = {a["key"]: a for a in ARQUETIPOS}
BENCAO_BY_KEY = {b["key"]: b for b in BENCAOS}
MARCA_BY_KEY = {m["key"]: m for m in MARCAS}
TERRA_BY_KEY = {t[0]: t for t in TERRAS}


# ---------------------------------------------------------------- utilidades
def _norm(text):
    """Comparação tolerante de nomes digitados na ficha ("Âncora" = "ancora")."""
    import unicodedata
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _find(catalog, typed):
    wanted = _norm(typed)
    if not wanted:
        return None
    for item in catalog:
        if _norm(item["name"]) == wanted or _norm(item["key"]) == wanted:
            return item
    return None


def uses_rules(system):
    """O sistema (o preset ou uma cópia dele) segue as regras de Limiar?"""
    return bool(system) and (system.data or {}).get("rules") == SLUG


def available(items, version):
    return [i for i in items if i.get("since", "0.23") <= version]


def affinity_count(arquetipo_key, level, version):
    """(mínimo, máximo) de afinidades que o personagem pode ter."""
    if version < "0.24":
        return 0, 0
    if arquetipo_key == "canalizador":
        extra = len([lv for lv in (6, 12, 18) if level >= lv])
        return 2 + extra, 2 + extra
    # Segunda Afinidade é um Aprimoramento a partir do nível 11.
    return 0, (2 if level >= 11 else 1)


def level_for_xp(xp):
    level = 1
    for lv in range(1, 21):
        if xp >= XP_TABLE[lv]:
            level = lv
    return level


def rules_payload():
    """Tudo o que o assistente de criação precisa, para conferir no navegador."""
    return {
        "versions": list(VERSIONS),
        "default_version": DEFAULT_VERSION,
        "attributes": ATTRIBUTES,
        "skills": [{"key": k, "name": n, "attr": a} for k, n, a in SKILLS],
        "terras": [{"key": k, "name": n, "custom": c} for k, n, c in TERRAS],
        "passados": PASSADOS,
        "arquetipos": ARQUETIPOS,
        "bencaos": BENCAOS,
        "marcas": MARCAS,
        "escolas": ESCOLAS,
        "dons": DONS_MENORES,
        "weapons": WEAPONS,
        "armors": ARMORS,
        "shields": SHIELDS,
        "kit_items": KIT_ITEMS,
        "budget": {"bencao": BENCAO_BUDGET, "sem_afinidade": SEM_AFINIDADE_BONUS,
                   "marca_max": MARCA_POINTS_MAX, "marcas_max": MARCAS_MAX,
                   "spend_max": BENCAO_SPEND_MAX},
    }


# ---------------------------------------------------------------- criação
def _as_list(value):
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if str(v)]
    if not value:
        return []
    return [str(value)]


def clean_choices(raw):
    """Normaliza o que veio do formulário do assistente."""
    raw = raw or {}
    version = raw.get("version") if raw.get("version") in VERSIONS else DEFAULT_VERSION
    attrs = raw.get("attributes") or {}
    return {
        "version": version,
        "name": str(raw.get("name") or "").strip()[:120],
        "concept": str(raw.get("concept") or "").strip()[:200],
        "terra": str(raw.get("terra") or ""),
        "contato": str(raw.get("contato") or "").strip()[:200],
        "passado": str(raw.get("passado") or ""),
        "arquetipo": str(raw.get("arquetipo") or ""),
        "afinidades": _as_list(raw.get("afinidades")),
        "principal": str(raw.get("principal") or ""),
        "attributes": {a["key"]: to_int(attrs.get(a["key"]), 1) for a in ATTRIBUTES},
        "skills": _as_list(raw.get("skills")),
        "bencaos": _as_list(raw.get("bencaos")),
        "marcas": _as_list(raw.get("marcas")),
        "dons": _as_list(raw.get("dons")),
        "weapon": str(raw.get("weapon") or ""),
        "armor": str(raw.get("armor") or ""),
        "shield": str(raw.get("shield") or ""),
    }


def free_skill_picks(choices):
    """Quantas perícias livres o personagem escolhe: 2 + Mente + repetidas."""
    passado = PASSADO_BY_KEY.get(choices["passado"])
    arquetipo = ARQUETIPO_BY_KEY.get(choices["arquetipo"])
    fixed = (passado["skills"] if passado else []) + (arquetipo["skills"] if arquetipo else [])
    repeated = len(fixed) - len(set(fixed))
    return 2 + max(0, choices["attributes"].get("mente", 0)) + repeated, set(fixed)


def bencao_budget(choices):
    """(orçamento total, pontos vindos das Marcas, bônus de quem não tem afinidade)."""
    marca_points = sum(MARCA_BY_KEY[m]["cost"] for m in choices["marcas"] if m in MARCA_BY_KEY)
    marca_points = min(marca_points, MARCA_POINTS_MAX)
    bonus = SEM_AFINIDADE_BONUS if (choices["version"] >= "0.24" and not choices["afinidades"]) else 0
    return BENCAO_BUDGET + marca_points + bonus, marca_points, bonus


def expected_dons(choices):
    count = 0
    if choices["arquetipo"] == "canalizador":
        count += 2
    if "dom_aprendido" in choices["bencaos"]:
        count += 1
    return count


def check_creation(choices):
    """Confere a criação. Devolve uma lista de {"level": erro|aviso, "step", "msg"}."""
    c = choices
    version = c["version"]
    out = []

    def err(step, msg):
        out.append({"level": "erro", "step": step, "msg": msg})

    def warn(step, msg):
        out.append({"level": "aviso", "step": step, "msg": msg})

    if not c["name"]:
        err("conceito", "Dê um nome ao personagem.")
    if c["terra"] not in TERRA_BY_KEY:
        err("conceito", "Escolha a terra natal.")
    passado = PASSADO_BY_KEY.get(c["passado"])
    if passado is None or passado["since"] > version:
        err("passado", "Escolha um passado%s." % (
            " (Quebra-Pacto só existe a partir da v0.24)" if passado else ""))
    arquetipo = ARQUETIPO_BY_KEY.get(c["arquetipo"])
    if arquetipo is None:
        err("arquetipo", "Escolha um arquétipo.")

    # Afinidade
    afinidades = c["afinidades"]
    if version >= "0.24":
        bad = [a for a in afinidades if a not in ESCOLA_BY_KEY]
        if bad:
            err("afinidade", "Escola desconhecida: %s." % ", ".join(bad))
        if len(set(afinidades)) != len(afinidades):
            err("afinidade", "A mesma escola foi escolhida duas vezes.")
        if arquetipo:
            low, high = affinity_count(arquetipo["key"], 1, version)
            if arquetipo["key"] == "canalizador" and len(afinidades) != 2:
                err("afinidade", "O Canalizador começa com exatamente duas afinidades.")
            elif arquetipo["key"] != "canalizador" and len(afinidades) > 1:
                err("afinidade", "Só o Canalizador começa com mais de uma afinidade.")
        if len(afinidades) >= 2 and c["principal"] not in afinidades:
            err("afinidade", "Com duas afinidades, escolha qual é a escola principal.")
    elif afinidades:
        err("afinidade", "Afinidade só existe a partir da v0.24.")

    # Atributos
    values = c["attributes"]
    zeros = [k for k, v in values.items() if v == 0]
    for attr in ATTRIBUTES:
        v = values[attr["key"]]
        if v < 0 or v > 3:
            err("atributos", "%s precisa ficar entre 0 e 3 na criação." % attr["name"])
    if len(zeros) > 1:
        err("atributos", "Só um atributo pode ser reduzido a 0.")
    total = sum(values.values())
    expected = len(ATTRIBUTES) + 4  # todos em 1, mais 4 pontos (o 0 devolve o ponto)
    if total > expected:
        err("atributos", "Pontos demais: a soma dos atributos é %d e o máximo é %d." % (total, expected))
    elif total < expected:
        warn("atributos", "Ainda sobram %d ponto(s) de atributo para distribuir." % (expected - total))

    # Perícias
    picks, fixed = free_skill_picks(c)
    chosen = [s for s in c["skills"] if s in SKILL_NAMES]
    unknown = [s for s in c["skills"] if s not in SKILL_NAMES]
    if unknown:
        err("pericias", "Perícia desconhecida: %s." % ", ".join(unknown))
    again = [SKILL_NAMES[s] for s in chosen if s in fixed]
    if again:
        err("pericias", "Já treinada pelo passado ou arquétipo: %s." % ", ".join(again))
    if len(set(chosen)) != len(chosen):
        err("pericias", "A mesma perícia foi marcada duas vezes.")
    free = len(set(chosen) - fixed)
    if free > picks:
        err("pericias", "Perícias demais: são %d escolhas livres (2 + Mente%s), e há %d marcadas." % (
            picks, " + repetidas" if picks > 2 + values.get("mente", 0) else "", free))
    elif free < picks:
        warn("pericias", "Faltam %d perícia(s) livre(s) para escolher." % (picks - free))

    # Bênçãos e Marcas
    budget, marca_points, bonus = bencao_budget(c)
    unknown = [b for b in c["bencaos"] if b not in BENCAO_BY_KEY]
    unknown += [m for m in c["marcas"] if m not in MARCA_BY_KEY]
    if unknown:
        err("vantagens", "Bênção ou Marca desconhecida: %s." % ", ".join(unknown))
    spent = sum(BENCAO_BY_KEY[b]["cost"] for b in c["bencaos"] if b in BENCAO_BY_KEY)
    raw_marca = sum(MARCA_BY_KEY[m]["cost"] for m in c["marcas"] if m in MARCA_BY_KEY)
    if len(c["marcas"]) > MARCAS_MAX:
        err("vantagens", "No máximo %d Marcas na criação." % MARCAS_MAX)
    if raw_marca > MARCA_POINTS_MAX:
        warn("vantagens", "As Marcas somam %d pontos, mas só %d contam." % (raw_marca, MARCA_POINTS_MAX))
    if spent > BENCAO_SPEND_MAX:
        err("vantagens", "No máximo %d pontos em Bênçãos na criação (há %d)." % (BENCAO_SPEND_MAX, spent))
    if spent > budget:
        err("vantagens", "As Bênçãos custam %d pontos e o orçamento é %d." % (spent, budget))
    elif spent < budget:
        warn("vantagens", "Sobram %d ponto(s) de Bênção. Pontos não gastos na criação são perdidos." % (
            budget - spent))
    if version >= "0.24" and "dom_aprendido" in c["bencaos"] and not afinidades:
        err("vantagens", "Dom Aprendido ensina um dom de uma das suas afinidades, e você não tem nenhuma.")

    # Dons
    need = expected_dons(c)
    dons = [d for d in c["dons"] if d in DOM_BY_KEY]
    if len(set(c["dons"])) != len(c["dons"]):
        err("dons", "O mesmo dom foi escolhido duas vezes.")
    for d in dons:
        dom = DOM_BY_KEY[d]
        if dom["since"] > version:
            err("dons", "%s só existe a partir da v0.24." % dom["name"])
        if version >= "0.24" and dom["school"] not in afinidades:
            err("dons", "%s é da escola %s, que não é uma afinidade sua." % (
                dom["name"], ESCOLA_BY_KEY[dom["school"]]["name"]))
    if len(dons) > need:
        err("dons", "Dons demais: você começa com %d." % need)
    elif len(dons) < need:
        err("dons", "Escolha mais %d dom(ns) menor(es)." % (need - len(dons)))

    # Equipamento
    if arquetipo:
        kit = arquetipo["kit"]
        weapons = {w["key"] for w in WEAPONS[kit["weapon"]]["items"]}
        if c["weapon"] not in weapons:
            err("equipamento", "Escolha a %s do kit." % WEAPONS[kit["weapon"]]["label"].lower())
        if kit["armor"]:
            armors = {a["key"] for a in ARMORS[kit["armor"]]["items"]}
            if c["armor"] not in armors:
                err("equipamento", "Escolha a %s do kit." % ARMORS[kit["armor"]]["label"].lower())
        elif c["armor"]:
            err("equipamento", "O kit do %s não tem armadura." % arquetipo["name"])
        if kit["shield"] and c["shield"] not in {s["key"] for s in SHIELDS}:
            err("equipamento", "Escolha o escudo do kit.")
        if not kit["shield"] and c["shield"]:
            err("equipamento", "O kit do %s não tem escudo." % arquetipo["name"])
        if kit["shield"] and c["weapon"] in ("arco_curto", "arco_longo", "besta_leve"):
            warn("equipamento", "Armas de Duas Mãos não permitem usar o escudo ao mesmo tempo.")
    return out


def derived(choices):
    """PV, PI, Defesa e carga de nível 1."""
    arquetipo = ARQUETIPO_BY_KEY.get(choices["arquetipo"])
    corpo = choices["attributes"].get("corpo", 0)
    alma = choices["attributes"].get("alma", 0)
    armor = armor_bonus(choices)
    return {
        "pv": (arquetipo["pv_base"] if arquetipo else 0) + corpo * 5,
        "pi": (arquetipo["pi_base"] if arquetipo else 0) + alma,
        "defesa": 10 + corpo * 2 + armor,
        "armadura": armor,
        "carga": 8 + corpo,
    }


def armor_bonus(choices):
    arquetipo = ARQUETIPO_BY_KEY.get(choices["arquetipo"])
    if not arquetipo:
        return 0
    kit = arquetipo["kit"]
    bonus = ARMORS[kit["armor"]]["defense"] if kit["armor"] else 0
    if kit["shield"] and choices["shield"]:
        bonus += 2
    return bonus


def _item(name, desc="", category="geral", weight=1, value=0, qty=1, equipped=False):
    return {"name": name, "desc": desc, "category": category, "weight": weight,
            "value": value, "qty": qty, "equipped": equipped}


def build_data(system, choices, money=None):
    """Ficha pronta a partir de uma criação já conferida."""
    from app import sheet as sheet_helper

    c = choices
    data = sheet_helper.blank_data(system)
    passado = PASSADO_BY_KEY[c["passado"]]
    arquetipo = ARQUETIPO_BY_KEY[c["arquetipo"]]
    terra = TERRA_BY_KEY[c["terra"]]
    stats = derived(c)

    for key, value in c["attributes"].items():
        data["attributes"][key] = value
    trained = set(passado["skills"]) | set(arquetipo["skills"]) | set(c["skills"])
    for key in trained:
        data["skills"].setdefault(key, {"value": 0, "train": 0, "prof": 0, "other": 0})
        data["skills"][key]["train"] = 5

    escolas = [ESCOLA_BY_KEY[a]["name"] for a in c["afinidades"]]
    principal = c["principal"] if len(c["afinidades"]) >= 2 else (c["afinidades"][0] if c["afinidades"] else "")
    meta = data["meta"]
    meta.update({
        "regras": "v" + c["version"],
        "arquetipo": arquetipo["name"],
        "passado": passado["name"],
        "terra": terra[1],
        "nivel": "1",
        "defesa": str(stats["defesa"]),
        "armadura": str(stats["armadura"]),
        "deslocamento": "10 m",
        "pv_base": str(arquetipo["pv_base"]),
        "pv_nivel": str(arquetipo["pv_nivel"]),
        "pi_base": str(arquetipo["pi_base"]),
        "pi_nivel": str(arquetipo["pi_nivel"]),
        "pv_extra": "0",
        "pi_extra": "0",
    })
    if c["version"] >= "0.24":
        meta["afinidades"] = ", ".join(escolas) if escolas else "Nenhuma"
        meta["escola_principal"] = ESCOLA_BY_KEY[principal]["name"] if principal else ""

    abilities = [
        {"name": "%s (passado)" % passado["ability"], "desc": passado["text"]},
        {"name": "%s (%s, N1)" % (arquetipo["n1"], arquetipo["name"]), "desc": arquetipo["n1_text"]},
        {"name": "Costume: %s" % terra[1],
         "desc": terra[2] + (" Contato: %s." % c["contato"] if c["contato"] else "")},
    ]
    for key in c["bencaos"]:
        b = BENCAO_BY_KEY[key]
        abilities.append({"name": "Bênção: %s" % b["name"], "desc": "%s (%d pontos)" % (b["effect"], b["cost"])})
    for key in c["marcas"]:
        m = MARCA_BY_KEY[key]
        abilities.append({"name": "Marca: %s" % m["name"], "desc": "%s (+%d pontos)" % (m["effect"], m["cost"])})
    if c["version"] >= "0.24" and not c["afinidades"]:
        abilities.append({"name": "Sem afinidade",
                          "desc": "Não emite pulso nenhum, nem ao usar relíquias. Ainda pode conduzir rituais."})
    data["abilities"] = abilities

    spells = []
    for key in c["dons"]:
        dom = DOM_BY_KEY[key]
        school = ESCOLA_BY_KEY[dom["school"]]
        spells.append({
            "name": dom["name"], "level": 1, "cost": "1 PI", "execution": "Ação",
            "range": dom["reach"], "duration": "",
            "desc": "Dom menor (DT 15) · %s · %s. %s" % (school["name"], school["entity"], dom["text"]),
            "prepared": True,
        })
    data["spells"] = spells

    kit = arquetipo["kit"]
    weapon = next(w for w in WEAPONS[kit["weapon"]]["items"] if w["key"] == c["weapon"])
    damage = WEAPONS[kit["weapon"]]["damage"]
    inventory = [_item(weapon["name"], "%s %s · %s" % (damage, weapon["type"], weapon["props"]),
                       "arma", 1, weapon["price"], equipped=True)]
    data["attacks"] = [{
        "name": weapon["name"], "test": "pontaria" if weapon["ranged"] else "luta", "bonus": 0,
        "damage": damage, "crit": "20: dano dobrado", "range": "à distância" if weapon["ranged"] else "corpo a corpo",
        "desc": "%s. %s" % (weapon["type"], weapon["props"]),
    }]
    if kit["armor"]:
        armor = next(a for a in ARMORS[kit["armor"]]["items"] if a["key"] == c["armor"])
        group = ARMORS[kit["armor"]]
        inventory.append(_item(armor["name"], "+%d de Defesa · Resiste %s · Fraca %s%s" % (
            group["defense"], armor["resist"], armor["weak"],
            " · " + group["penalty"] if group.get("penalty") else ""), "proteção", 1, 0, equipped=True))
    if kit["shield"]:
        shield = next(s for s in SHIELDS if s["key"] == c["shield"])
        inventory.append(_item(shield["name"], "+2 de Defesa · " + shield["effect"], "proteção", 1, 0,
                               equipped=True))
    for key in kit["items"]:
        item = KIT_ITEMS[key]
        inventory.append(_item(item["name"], item["desc"], "ferramenta", 1, item["value"]))
    for key in c["afinidades"]:
        escola = ESCOLA_BY_KEY[key]
        inventory.append(_item("Frasco de %s (5 doses)" % escola["fuel"].lower(),
                               "Combustível da %s. Uma dose queima por uma cena." % escola["name"],
                               "consumível", 1, escola["price"] * 5))
    data["inventory"] = inventory

    if money is not None:
        data["money"]["dr"] = money
    data["creation"] = dict(c)
    data["xp"] = 0
    data, _ = sheet_helper.apply_formulas(system, data)
    for key in ("pv", "pi"):
        if key in data["bars"]:
            data["bars"][key]["current"] = data["bars"][key]["max"]
    if "dissonancia" in data["bars"]:
        data["bars"]["dissonancia"]["current"] = 0
    return data


def roll_money():
    a, b = dice.die(6), dice.die(6)
    return (a + b) * 10, "2d6 × 10 = (%d + %d) × 10" % (a, b)


# ---------------------------------------------------------------- ficha em jogo
def check_sheet(character):
    """Confere uma ficha de Limiar em qualquer nível. Lista de {"level", "msg"}."""
    data = character.data or {}
    meta = data.get("meta") or {}
    out = []

    def err(msg):
        out.append({"level": "erro", "msg": msg})

    def warn(msg):
        out.append({"level": "aviso", "msg": msg})

    version = "0.24" if "0.24" in str(meta.get("regras", "")) else "0.23"
    level = to_int(meta.get("nivel"), 0)
    if level < 1 or level > 20:
        err("O nível precisa estar entre 1 e 20 (campo Nível).")
        level = max(1, min(20, level))
    xp = to_int(data.get("xp"), 0)
    if xp < XP_TABLE[level]:
        warn("O nível %d pede %d XP, e a ficha tem %d." % (level, XP_TABLE[level], xp))
    elif level < 20 and xp >= XP_TABLE[level + 1]:
        warn("Com %d XP o personagem já pode estar no nível %d." % (xp, level_for_xp(xp)))

    attrs = data.get("attributes") or {}
    values = {a["key"]: to_int(attrs.get(a["key"]), 1) for a in ATTRIBUTES}
    for attr in ATTRIBUTES:
        v = values[attr["key"]]
        if v < 0 or v > 5:
            err("%s precisa ficar entre 0 e 5." % attr["name"])
        elif v > 3 and level < ATTRIBUTE_LEVELS[0]:
            err("%s está em %d, mas na criação o máximo é 3 e o primeiro +1 vem no nível 8." % (
                attr["name"], v))
    bumps = len([lv for lv in ATTRIBUTE_LEVELS if level >= lv])
    expected = len(ATTRIBUTES) + 4 + bumps
    total = sum(values.values())
    if total > expected:
        err("A soma dos atributos é %d; no nível %d o máximo é %d." % (total, level, expected))
    elif total < expected:
        warn("A soma dos atributos é %d; no nível %d dá para chegar a %d." % (total, level, expected))

    arquetipo = _find(ARQUETIPOS, meta.get("arquetipo"))
    passado = _find(PASSADOS, meta.get("passado"))
    if arquetipo is None:
        err("Arquétipo não reconhecido: escreva Vanguarda, Decifrador, Âncora ou Canalizador.")
    if passado is None:
        warn("Passado não reconhecido entre os do Livro do Jogador (pode ser um criado pela mesa).")

    skills = data.get("skills") or {}
    grades = {k: to_int((skills.get(k) or {}).get("train"), 0) for k, _, _ in SKILLS}
    for key, grade in grades.items():
        if grade >= 15 and level < 18:
            err("%s está em Mestre, que só é possível a partir do nível 18." % SKILL_NAMES[key])
        elif grade >= 10 and level < 10:
            err("%s está em Avançado, que só é possível a partir do nível 10." % SKILL_NAMES[key])
    for source in (passado, arquetipo):
        if source:
            missing = [SKILL_NAMES[k] for k in source["skills"] if grades.get(k, 0) < 5]
            if missing:
                err("%s treina %s, que está destreinada na ficha." % (source["name"], ", ".join(missing)))
    steps = sum(g // 5 for g in grades.values())
    fixed = (passado["skills"] if passado else []) + (arquetipo["skills"] if arquetipo else [])
    creation = data.get("creation") or {}
    mente_inicial = to_int((creation.get("attributes") or {}).get("mente"), values["mente"])
    base = len(set(fixed)) + (len(fixed) - len(set(fixed))) + 2 + mente_inicial if (passado and arquetipo) else None
    gained = len([lv for lv in SKILL_GRADE_LEVELS if level >= lv])
    if base is not None:
        allowed = base + gained
        if steps > allowed:
            warn("A ficha tem %d graus de perícia; no nível %d o esperado é %d. Cada Aprimoramento "
                 "Estudo dá mais 2." % (steps, level, allowed))
        elif steps < allowed:
            warn("A ficha tem %d graus de perícia; no nível %d dá para ter %d." % (steps, level, allowed))

    if arquetipo:
        labels = {"pv_base": "PV base", "pv_nivel": "PV por nível par",
                  "pi_base": "PI base", "pi_nivel": "PI por nível par"}
        for key, label in labels.items():
            if to_int(meta.get(key), -1) != arquetipo[key]:
                err("%s deveria ser %d para %s." % (label, arquetipo[key], arquetipo["name"]))
        armadura = to_int(meta.get("armadura"), 0)
        defesa = to_int(meta.get("defesa"), 0)
        if defesa and defesa != 10 + values["corpo"] * 2 + armadura:
            warn("Defesa %d, mas 10 + Corpo × 2 + armadura dá %d." % (
                defesa, 10 + values["corpo"] * 2 + armadura))

    if version >= "0.24" and arquetipo:
        typed = [s.strip() for s in re.split(r"[,;/]", str(meta.get("afinidades") or "")) if s.strip()]
        typed = [t for t in typed if _norm(t) not in ("nenhuma", "")]
        escolas = [_find(ESCOLAS, t) for t in typed]
        if any(e is None for e in escolas):
            err("Afinidade não reconhecida. As escolas são: %s." % ", ".join(e["name"] for e in ESCOLAS))
        low, high = affinity_count(arquetipo["key"], level, version)
        if len(typed) < low:
            err("No nível %d, o Canalizador tem %d afinidades (a ficha lista %d)." % (level, low, len(typed)))
        elif len(typed) > high:
            err("No nível %d, %s pode ter no máximo %d afinidade(s)." % (level, arquetipo["name"], high))
        if len(typed) >= 2 and not _find([e for e in escolas if e], meta.get("escola_principal")):
            warn("Com mais de uma afinidade, indique a escola principal.")

    if creation:
        problems = [p for p in check_creation(clean_choices(creation)) if p["level"] == "erro"
                    and p["step"] in ("vantagens", "dons")]
        for p in problems:
            err("Na criação: " + p["msg"])
    return out
