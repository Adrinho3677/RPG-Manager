# -*- coding: utf-8 -*-
"""Funções auxiliares usadas pelas views e pelos templates."""
import re
import unicodedata

from markupsafe import Markup, escape


def slugify(value, fallback="campo"):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return value or fallback


_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def clean_color(value, fallback="#8b5cf6"):
    """Só aceita cores hexadecimais — o valor vai direto para um atributo style."""
    value = (value or "").strip()
    return value if _HEX_COLOR.match(value) else fallback


def unique_key(base, existing):
    """Garante uma chave única dentro de uma coleção de chaves já usadas."""
    key = slugify(base)
    if key not in existing:
        return key
    i = 2
    while "%s_%d" % (key, i) in existing:
        i += 1
    return "%s_%d" % (key, i)


_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_ITALIC = re.compile(r"(?<!\*)\*([^*\n]+?)\*(?!\*)")
_CODE = re.compile(r"`([^`\n]+?)`")


def rich_text(value):
    """Markdown mínimo e seguro: escapa tudo e aceita **negrito**, *itálico*,
    `código`, títulos com # e listas com - ou *."""
    if not value:
        return Markup("")
    html_lines = []
    in_list = False
    for raw_line in str(value).splitlines():
        line = escape(raw_line.rstrip())
        stripped = str(line).strip()

        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue

        heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        bullet = re.match(r"^[-*]\s+(.*)$", stripped)

        if bullet:
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append("<li>%s</li>" % _inline(bullet.group(1)))
            continue

        if in_list:
            html_lines.append("</ul>")
            in_list = False

        if heading:
            level = min(len(heading.group(1)) + 2, 6)
            html_lines.append("<h%d>%s</h%d>" % (level, _inline(heading.group(2)), level))
        else:
            html_lines.append("<p>%s</p>" % _inline(stripped))

    if in_list:
        html_lines.append("</ul>")
    return Markup("".join(html_lines))


def _inline(text):
    text = _CODE.sub(r"<code>\1</code>", text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return text


def excerpt(value, limit=160):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


def ability_modifier(score):
    """Modificador no estilo D&D: (valor - 10) // 2."""
    try:
        return (int(score) - 10) // 2
    except (TypeError, ValueError):
        return 0


def signed(number):
    try:
        number = int(number)
    except (TypeError, ValueError):
        return "+0"
    return "+%d" % number if number >= 0 else str(number)


def to_int(value, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default


def to_float(value, default=0.0):
    """Aceita tanto 1.5 quanto 1,5 — gente escreve peso dos dois jeitos."""
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError, AttributeError):
        return default


def pretty_number(value):
    """Mostra 3 em vez de 3.0, mas mantém 2.5."""
    number = to_float(value)
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return ("%.2f" % number).rstrip("0").rstrip(".").replace(".", ",")


def local_time(value, fmt="%d/%m/%Y %H:%M"):
    """Formata um datetime guardado em UTC no fuso configurado (TIMEZONE)."""
    if value is None:
        return ""
    from datetime import timezone
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from flask import current_app

    try:
        zone = ZoneInfo(current_app.config.get("TIMEZONE") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.utc
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(zone).strftime(fmt)
