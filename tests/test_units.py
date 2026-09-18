# -*- coding: utf-8 -*-
"""Módulos puros: fórmulas e dados."""
import collections

import pytest

from app.dice import DiceError, roll_check, roll_formula
from app.formula import FormulaError, evaluate, validate


# ------------------------------------------------------------------ fórmulas
@pytest.mark.parametrize("expression, expected", [
    ("20 + VIG * 4", 32),
    ("20+vig*4", 32),                 # sem espaços e sem diferença de caixa
    ("max(1, NEX / 5)", 7),
    ("(nex / 5) * vig", 21),
    ("-VIG + 10", 7),
    ("7.5 * 2", 15),
    ("min(5,3)", 3),                  # vírgula separa argumentos, não é decimal
    ("max(1,VIG)", 3),
    ("39 / 5", 7),                    # divisão arredonda para baixo
])
def test_formula_calcula(expression, expected):
    assert evaluate(expression, {"VIG": 3, "nex": 35}) == expected


@pytest.mark.parametrize("malicious", [
    '__import__("os").system("x")',
    "open(1)",
    "VIG ** 99",
    "().__class__",
    "lambda: 1",
    "9" * 200,
])
def test_formula_recusa_codigo(malicious):
    with pytest.raises(FormulaError):
        evaluate(malicious, {"VIG": 3})


@pytest.mark.parametrize("broken, message", [
    ("abc + 1", "Não conheço"),
    ("10 / 0", "Divisão por zero"),
    ("(1 + 2", "terminou"),
    ("", "vazia"),
])
def test_formula_explica_o_erro(broken, message):
    with pytest.raises(FormulaError) as error:
        evaluate(broken, {})
    assert message in str(error.value)


def test_validate_usa_nomes_do_sistema():
    assert validate("20 + VIG", {"VIG"}) is None
    assert "XYZ" in validate("20 + XYZ", {"VIG"})


# ---------------------------------------------------------------------- dados
def test_d20_cobre_todas_as_faces():
    faces = collections.Counter(roll_check("d20_mod")["result"] for _ in range(4000))
    assert sorted(faces) == list(range(1, 21))


def test_ordem_pega_o_maior_e_atributo_zero_pega_o_pior():
    for _ in range(200):
        r = roll_check("keep_highest_d20", dice=3, bonus=5)
        faces = [int(x) for x in r["detail"].split("[")[1].split("]")[0].split(",")]
        assert len(faces) == 3 and r["result"] == max(faces) + 5
        zero = roll_check("keep_highest_d20", dice=0)
        faces0 = [int(x) for x in zero["detail"].split("[")[1].split("]")[0].split(",")]
        assert len(faces0) == 2 and zero["result"] == min(faces0)


def test_parada_rola_exatamente_a_quantidade_pedida():
    """Regressão: a perícia mandava o total como dados E como bônus, dobrando a parada."""
    r = roll_check("pool_d10", dice=4, bonus=0)
    assert r["detail"].startswith("4d10")
    extra = roll_check("pool_d10", dice=4, bonus=2)
    assert extra["detail"].startswith("6d10")


def test_d100_classifica_pelo_alvo():
    for _ in range(300):
        r = roll_check("d100_under", target=50)
        value = r["result"]
        if value <= 10:
            assert "EXTREMO" in r["detail"]
        elif value <= 25:
            assert "BOM" in r["detail"]
        elif value <= 50:
            assert "NORMAL" in r["detail"]
        else:
            assert "FALHA" in r["detail"]


def test_formula_de_dados():
    r = roll_formula("2d6+3")
    assert 5 <= r["result"] <= 15 and r["detail"].startswith("2d6")
    for bad in ("2d", "1000d6", "d1", "abc", ""):
        with pytest.raises(DiceError):
            roll_formula(bad)


def test_horario_convertido_para_o_fuso_configurado(app):
    from datetime import datetime
    from app.utils import local_time
    with app.app_context():
        app.config["TIMEZONE"] = "America/Sao_Paulo"
        assert local_time(datetime(2026, 9, 16, 23, 14), "%H:%M") == "20:14"
        app.config["TIMEZONE"] = "Fuso/Inexistente"
        assert local_time(datetime(2026, 9, 16, 23, 14), "%H:%M") == "23:14"
