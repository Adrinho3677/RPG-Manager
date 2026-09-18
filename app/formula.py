# -*- coding: utf-8 -*-
"""Avaliador de fórmulas das barras, como "20 + VIG * 4" ou "max(1, NEX / 5)".

Não usa eval() nem o módulo ast: é um analisador próprio que só conhece
números, nomes de atributos/campos, + - * /, parênteses e min/max. Qualquer
outra coisa vira FormulaError. Assim uma fórmula escrita por um usuário nunca
executa código.

A divisão arredonda para baixo, como a maioria das regras de RPG faz.
"""
import re

MAX_LENGTH = 160
MAX_TOKENS = 80
LIMIT = 1000000

_TOKEN = re.compile(
    r"\s*(?:"
    # Só ponto como decimal: a vírgula separa argumentos, e "min(5,3)"
    # não pode virar min(5.3).
    r"(?P<num>\d+(?:\.\d+)?)"
    r"|(?P<name>[A-Za-zÀ-ÿ_][A-Za-zÀ-ÿ0-9_]*)"
    r"|(?P<op>[-+*/(),])"
    r")"
)

FUNCTIONS = {"min": min, "max": max}


class FormulaError(ValueError):
    pass


def tokenize(text):
    text = (text or "").strip()
    if not text:
        raise FormulaError("A fórmula está vazia.")
    if len(text) > MAX_LENGTH:
        raise FormulaError("A fórmula passa de %d caracteres." % MAX_LENGTH)

    tokens, pos = [], 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            rest = text[pos:].strip()
            if not rest:
                break
            raise FormulaError("Não entendi a partir de “%s”." % rest[:12])
        if match.group("num") is not None:
            tokens.append(("num", float(match.group("num"))))
        elif match.group("name") is not None:
            tokens.append(("name", match.group("name")))
        elif match.group("op") is not None:
            tokens.append(("op", match.group("op")))
        pos = match.end()

    if len(tokens) > MAX_TOKENS:
        raise FormulaError("A fórmula é longa demais.")
    return tokens


class _Parser(object):
    def __init__(self, tokens, variables):
        self.tokens = tokens
        self.pos = 0
        # nomes sem diferença de maiúsculas: VIG, vig e Vig são o mesmo
        self.variables = {str(k).lower(): v for k, v in (variables or {}).items()}

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def take(self, kind=None, value=None):
        token = self.peek()
        if token[0] is None:
            raise FormulaError("A fórmula terminou antes da hora.")
        if (kind and token[0] != kind) or (value and token[1] != value):
            raise FormulaError("Esperava “%s” e encontrei “%s”." % (value or kind, token[1]))
        self.pos += 1
        return token

    def parse(self):
        value = self.expr()
        if self.pos != len(self.tokens):
            raise FormulaError("Sobrou “%s” no fim da fórmula." % self.peek()[1])
        return value

    def expr(self):
        value = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            right = self.term()
            value = value + right if op == "+" else value - right
            self.check(value)
        return value

    def term(self):
        value = self.unary()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            right = self.unary()
            if op == "*":
                value = value * right
            else:
                if right == 0:
                    raise FormulaError("Divisão por zero.")
                value = value // right
            self.check(value)
        return value

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            return -self.unary()
        if self.peek() == ("op", "+"):
            self.take()
            return self.unary()
        return self.primary()

    def primary(self):
        kind, value = self.peek()
        if kind == "num":
            self.take()
            return value
        if kind == "op" and value == "(":
            self.take()
            inner = self.expr()
            self.take("op", ")")
            return inner
        if kind == "name":
            self.take()
            lowered = value.lower()
            if self.peek() == ("op", "("):
                if lowered not in FUNCTIONS:
                    raise FormulaError("Função desconhecida: %s. Use min ou max." % value)
                self.take()
                args = [self.expr()]
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.expr())
                self.take("op", ")")
                return FUNCTIONS[lowered](args)
            if lowered not in self.variables:
                raise FormulaError("Não conheço “%s”." % value)
            return float(self.variables[lowered])
        if kind is None:
            raise FormulaError("A fórmula terminou antes da hora.")
        raise FormulaError("Não esperava “%s” aqui." % value)

    @staticmethod
    def check(value):
        if abs(value) > LIMIT:
            raise FormulaError("O resultado ficou grande demais.")


def evaluate(text, variables):
    """Calcula a fórmula e devolve um inteiro (arredondado para baixo)."""
    value = _Parser(tokenize(text), variables).parse()
    return int(value // 1)


def validate(text, names):
    """Confere a fórmula sem valores reais. Devolve a mensagem de erro ou None."""
    try:
        evaluate(text, {name: 1 for name in names})
    except FormulaError as error:
        return str(error)
    return None


def character_variables(attributes, meta):
    """Nomes que uma fórmula pode usar numa ficha.

    Cada atributo responde pela chave e pela sigla (VIG, vigor...) com o valor
    usado nas rolagens — em D&D, isso é o modificador. Campos de identidade
    numéricos (NEX, nível, bônus de proficiência) respondem pela chave.
    """
    from app.utils import to_int

    variables = {}
    for field_key, raw in (meta or {}).items():
        # Campo vazio ou com texto vale 0: numa ficha recém-criada o NEX ainda
        # está em branco, e "NEX / 5" não pode quebrar por isso.
        try:
            variables[field_key] = float(str(raw).strip().replace(",", "."))
        except (TypeError, ValueError):
            variables[field_key] = 0
    for attr in attributes:
        value = attr.get("effective", to_int(attr.get("value"), 0))
        variables[attr["key"]] = value
        if attr.get("abbr"):
            variables[attr["abbr"]] = value
    return variables


def known_names(system_data):
    """Nomes válidos para validar fórmulas no editor de sistemas."""
    names = set()
    for attr in (system_data or {}).get("attributes") or []:
        if attr.get("key"):
            names.add(attr["key"])
        if attr.get("abbr"):
            names.add(attr["abbr"])
    for field in (system_data or {}).get("meta_fields") or []:
        if field.get("key"):
            names.add(field["key"])
    return names
