# -*- coding: utf-8 -*-
"""Calendário do mundo: datas dentro do jogo.

Cada campanha define seus meses (nome e quantidade de dias), os dias da
semana e uma era ("DR", "Era do Trono"...). Uma data é guardada como um número
só — dias desde o dia 1 do mês 1 do ano 1 — o que deixa somar dias, comparar e
ordenar trivial. Não há ano bissexto: calendários de fantasia raramente têm, e
o mestre sempre pode ajustar a data de "hoje" à mão.

Campaign.calendar (JSON):
    months         [{name, days}]
    weekdays       [nomes]  (pode ser vazio)
    first_weekday  dia da semana do dia 1/1/1
    era            texto depois do ano
    today          data atual do mundo (número de dias)
    minute         hora de "hoje", em minutos desde a meia-noite (ou None)

Linha do tempo e sessões guardam dia (world_day) e, se quiser, hora
(world_minute). Dia de 24 horas em qualquer calendário.
"""
from app.utils import to_int

MAX_MONTHS = 24
MAX_DAYS = 400
MAX_YEAR = 100000

PRESETS = {
    "gregoriano": {
        "label": "Gregoriano (Janeiro a Dezembro)",
        "months": [("Janeiro", 31), ("Fevereiro", 28), ("Março", 31), ("Abril", 30),
                   ("Maio", 31), ("Junho", 30), ("Julho", 31), ("Agosto", 31),
                   ("Setembro", 30), ("Outubro", 31), ("Novembro", 30), ("Dezembro", 31)],
        "weekdays": ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"],
    },
    "simples": {
        "label": "Simples (12 meses de 30 dias)",
        "months": [("Mês %d" % n, 30) for n in range(1, 13)],
        "weekdays": ["1º dia", "2º dia", "3º dia", "4º dia", "5º dia", "6º dia", "7º dia"],
    },
}


class CalendarError(ValueError):
    pass


def from_preset(name, era="", year=1):
    preset = PRESETS.get(name) or PRESETS["gregoriano"]
    calendar = normalize({
        "months": [{"name": m, "days": d} for m, d in preset["months"]],
        "weekdays": list(preset["weekdays"]),
        "era": era,
    })
    calendar["today"] = to_ordinal(calendar, year, 1, 1)
    return calendar


def normalize(raw):
    """Calendário válido ou None (campanha sem calendário configurado)."""
    if not isinstance(raw, dict):
        return None
    months = []
    for month in raw.get("months") or []:
        if not isinstance(month, dict):
            continue
        name = str(month.get("name") or "").strip()[:40]
        days = to_int(month.get("days"), 0)
        if name and 1 <= days <= MAX_DAYS:
            months.append({"name": name, "days": days})
    if not months:
        return None
    weekdays = [str(w).strip()[:20] for w in raw.get("weekdays") or [] if str(w).strip()][:14]
    year_length = sum(m["days"] for m in months[:MAX_MONTHS])
    return {
        "months": months[:MAX_MONTHS],
        "weekdays": weekdays,
        "first_weekday": to_int(raw.get("first_weekday"), 0) % (len(weekdays) or 1),
        "era": str(raw.get("era") or "").strip()[:20],
        "today": max(0, min(MAX_YEAR * year_length, to_int(raw.get("today"), 0))),
        # Hora de "hoje" em minutos desde a meia-noite (None = sem hora marcada).
        "minute": _minute_or_none(raw.get("minute")),
    }


def parse_months(text):
    """Texto "Nome: dias" (um mês por linha) em lista de meses."""
    months = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        name, _, days = line.rpartition(":")
        if not name.strip():
            raise CalendarError("Use uma linha por mês, no formato “Nome: dias”.")
        days = to_int(days.strip(), 0)
        if not 1 <= days <= MAX_DAYS:
            raise CalendarError("“%s”: o mês precisa ter de 1 a %d dias." % (name.strip(), MAX_DAYS))
        months.append({"name": name.strip()[:40], "days": days})
    if not months:
        raise CalendarError("O calendário precisa de pelo menos um mês.")
    if len(months) > MAX_MONTHS:
        raise CalendarError("No máximo %d meses." % MAX_MONTHS)
    return months


def year_length(calendar):
    return sum(m["days"] for m in calendar["months"])


def to_ordinal(calendar, year, month, day):
    """(ano, mês 1.., dia 1..) em número de dias. Valida os limites."""
    year, month, day = to_int(year, 0), to_int(month, 0), to_int(day, 0)
    if not 1 <= year <= MAX_YEAR:
        raise CalendarError("Ano fora do intervalo (1 a %d)." % MAX_YEAR)
    if not 1 <= month <= len(calendar["months"]):
        raise CalendarError("Mês inválido.")
    days = calendar["months"][month - 1]["days"]
    if not 1 <= day <= days:
        raise CalendarError("%s tem %d dias." % (calendar["months"][month - 1]["name"], days))
    before = sum(m["days"] for m in calendar["months"][:month - 1])
    return (year - 1) * year_length(calendar) + before + day - 1


def from_ordinal(calendar, ordinal):
    """Número de dias em (ano, mês 1.., dia 1..)."""
    length = year_length(calendar)
    ordinal = max(0, int(ordinal))
    year, rest = divmod(ordinal, length)
    for index, month in enumerate(calendar["months"]):
        if rest < month["days"]:
            return year + 1, index + 1, rest + 1
        rest -= month["days"]
    return year + 1, len(calendar["months"]), calendar["months"][-1]["days"]  # inalcançável


def weekday(calendar, ordinal):
    if not calendar["weekdays"]:
        return None
    return calendar["weekdays"][(ordinal + calendar["first_weekday"]) % len(calendar["weekdays"])]


def format_date(calendar, ordinal, with_weekday=False, minute=None):
    if calendar is None or ordinal is None:
        return ""
    year, month, day = from_ordinal(calendar, ordinal)
    text = "%d de %s de %d" % (day, calendar["months"][month - 1]["name"], year)
    if calendar["era"]:
        text += " " + calendar["era"]
    if with_weekday and calendar["weekdays"]:
        text = "%s, %s" % (weekday(calendar, ordinal), text)
    if minute is not None:
        text += ", " + format_time(minute)
    return text


# ------------------------------------------------------------------ horas
MINUTES_PER_DAY = 24 * 60


def _minute_or_none(value):
    if value is None or value == "":
        return None
    minute = to_int(value, -1)
    return minute if 0 <= minute < MINUTES_PER_DAY else None


def parse_time(text):
    """ "14:30", "14h30", "14h", "9" → minutos desde a meia-noite. Vazio → None."""
    import re
    text = (text or "").strip().lower()
    if not text:
        return None
    match = re.fullmatch(r"(\d{1,2})\s*(?:[:h]\s*(\d{1,2})?)?\s*(?:min)?", text)
    if not match:
        raise CalendarError("Hora inválida: use algo como 14:30.")
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    if hour > 23 or minute > 59:
        raise CalendarError("Hora inválida: vai de 00:00 a 23:59.")
    return hour * 60 + minute


def format_time(minute):
    return "%02d:%02d" % divmod(int(minute), 60) if minute is not None else ""


def time_from_form(form, prefix="world", has_date=True):
    minute = parse_time(form.get("%s_time" % prefix))
    if minute is not None and not has_date:
        raise CalendarError("Informe a data junto com a hora.")
    return minute


def advance(calendar, days=0, hours=0):
    """Anda o "hoje" do mundo. Horas que passam da meia-noite viram dias."""
    total = (calendar["minute"] or 0) + int(hours) * 60 if hours else calendar["minute"]
    if total is not None:
        extra, total = divmod(total, MINUTES_PER_DAY)
        days += extra
    calendar["today"] = max(0, calendar["today"] + int(days))
    calendar["minute"] = total
    return calendar


def chronology(day, minute):
    """Chave de ordenação: dia e, dentro do dia, a hora (sem hora vem primeiro)."""
    return (day, -1 if minute is None else minute)


def month_grid(calendar, year, month):
    """Semanas do mês para desenhar a folhinha: listas de (dia, ordinal) ou None."""
    first = to_ordinal(calendar, year, month, 1)
    days = calendar["months"][month - 1]["days"]
    width = len(calendar["weekdays"]) or 7
    offset = ((first + calendar["first_weekday"]) % width) if calendar["weekdays"] else 0
    cells = [None] * offset + [(d, first + d - 1) for d in range(1, days + 1)]
    while len(cells) % width:
        cells.append(None)
    return [cells[i:i + width] for i in range(0, len(cells), width)]


def date_from_form(calendar, form, prefix="world"):
    """Lê dia/mês/ano de um formulário. Tudo vazio = sem data (None)."""
    if calendar is None:
        return None
    parts = [(form.get("%s_%s" % (prefix, part)) or "").strip() for part in ("day", "month", "year")]
    if not any(parts):
        return None
    return to_ordinal(calendar, parts[2], parts[1], parts[0])
