# -*- coding: utf-8 -*-
import copy
import json

from flask import (Blueprint, Response, abort, flash, redirect, render_template, request,
                   url_for)
from flask_login import current_user, login_required

from app.extensions import db
from app.models import GameSystem
from app.presets import GENERICO
from app.formula import known_names, validate as validate_formula
from app.sheet import REST_MODES
from app.utils import clean_color, slugify, to_float, to_int, unique_key

bp = Blueprint("systems", __name__, url_prefix="/sistemas")

DISPLAY_CHOICES = [
    ("number", "Número puro (ex.: Ordem Paranormal, 0 a 5)"),
    ("modifier", "Valor com modificador calculado (ex.: D&D, 10 → +0)"),
    ("raw_modifier", "Já é o modificador (ex.: Tormenta 20)"),
    ("percent", "Porcentagem (ex.: Chamado de Cthulhu)"),
    ("dots", "Pontos/bolinhas (ex.: Vampiro, 1 a 5)"),
]

SKILL_MODE_CHOICES = [
    ("training", "Graus de treinamento (Destreinado/Treinado/Veterano/Expert)"),
    ("proficiency", "Proficiência (marca e soma o bônus de proficiência)"),
    ("percent", "Valor percentual próprio"),
    ("dots", "Pontos somados ao atributo"),
    ("bonus", "Bônus numérico simples"),
]

INVENTORY_MODES = [
    ("none", "Sem controle de carga"),
    ("weight", "Por peso (kg, lb...)"),
    ("slots", "Por espaços/slots"),
]

DEFAULT_LABELS = {
    "attacks": "Ataques",
    "spells": "Magias",
    "spell_level": "Círculo",
    "abilities": "Habilidades",
}

ROLL_CHOICES = [
    ("d20_mod", "1d20 + modificador"),
    ("keep_highest_d20", "Vários d20, pega o maior (Ordem Paranormal)"),
    ("d100_under", "1d100, precisa rolar igual ou abaixo"),
    ("pool_d10", "Parada de dados d10, sucesso em 6+"),
    ("d6_pool", "Parada de dados d6, sucesso em 5+"),
]


def owned_or_404(system_id):
    system = db.get_or_404(GameSystem, system_id)
    if not system.editable_by(current_user):
        abort(403)
    return system


@bp.route("/")
@login_required
def index():
    presets = GameSystem.query.filter_by(is_preset=True).order_by(GameSystem.name).all()
    mine = (
        GameSystem.query.filter_by(owner_id=current_user.id, is_preset=False)
        .order_by(GameSystem.name)
        .all()
    )
    return render_template("systems/index.html", presets=presets, mine=mine)


@bp.route("/<int:system_id>")
@login_required
def detail(system_id):
    system = db.get_or_404(GameSystem, system_id)
    if not system.usable_by(current_user):
        abort(403)
    return render_template("systems/detail.html", system=system,
                           warnings=formula_warnings(system.data))


@bp.route("/<int:system_id>/duplicar", methods=["POST"])
@login_required
def duplicate(system_id):
    source = db.get_or_404(GameSystem, system_id)
    if not source.usable_by(current_user):
        abort(403)
    clone = GameSystem(
        name="%s (minha versão)" % source.name,
        slug=slugify(source.name) + "-copia",
        description=source.description,
        is_preset=False,
        owner_id=current_user.id,
        data=copy.deepcopy(source.data or {}),
    )
    db.session.add(clone)
    db.session.commit()
    flash("Sistema duplicado. Agora é só editar do seu jeito.", "success")
    return redirect(url_for("systems.edit", system_id=clone.id))


@bp.route("/novo", methods=["GET", "POST"])
@login_required
def create():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip() or "Novo sistema"
        base_id = to_int(request.form.get("base"), 0)
        base_data = copy.deepcopy(GENERICO)
        if base_id:
            base = db.session.get(GameSystem, base_id)
            if base and base.usable_by(current_user):
                base_data = copy.deepcopy(base.data or {})
        system = GameSystem(
            name=name,
            slug=slugify(name),
            description=(request.form.get("description") or "").strip(),
            is_preset=False,
            owner_id=current_user.id,
            data=base_data,
        )
        db.session.add(system)
        db.session.commit()
        flash("Sistema criado. Monte a ficha abaixo.", "success")
        return redirect(url_for("systems.edit", system_id=system.id))

    bases = GameSystem.query.filter(
        (GameSystem.is_preset.is_(True)) | (GameSystem.owner_id == current_user.id)
    ).order_by(GameSystem.is_preset.desc(), GameSystem.name).all()
    return render_template("systems/new.html", bases=bases)


@bp.route("/<int:system_id>/editar", methods=["GET", "POST"])
@login_required
def edit(system_id):
    system = owned_or_404(system_id)

    if request.method == "POST":
        raw = (request.form.get("payload") or "").strip()
        try:
            payload = json.loads(raw) if raw else None
        except ValueError:
            payload = None
        # Sem payload válido não salvamos nada: gravar um dicionário vazio
        # apagaria todos os atributos, barras e perícias do sistema.
        if not isinstance(payload, dict) or not payload:
            flash("Não consegui ler os dados do editor, então nada foi alterado. "
                  "Recarregue a página e tente de novo.", "error")
            return redirect(url_for("systems.edit", system_id=system.id))

        system.name = (request.form.get("name") or system.name).strip()
        system.slug = slugify(system.name)
        system.description = (request.form.get("description") or "").strip()
        system.data = clean_payload(payload)
        db.session.commit()
        flash("Sistema salvo.", "success")
        for warning in formula_warnings(system.data):
            flash(warning, "warning")
        return redirect(url_for("systems.detail", system_id=system.id))

    return render_template(
        "systems/edit.html",
        system=system,
        display_choices=DISPLAY_CHOICES,
        skill_mode_choices=SKILL_MODE_CHOICES,
        roll_choices=ROLL_CHOICES,
        inventory_modes=INVENTORY_MODES,
        rest_modes=REST_MODES,
        default_labels=DEFAULT_LABELS,
        payload=json.dumps(system.data or {}, ensure_ascii=False),
    )


@bp.route("/<int:system_id>/excluir", methods=["POST"])
@login_required
def delete(system_id):
    system = owned_or_404(system_id)
    if system.campaigns.count():
        flash("Este sistema está em uso por uma campanha e não pode ser excluído.", "error")
        return redirect(url_for("systems.index"))
    db.session.delete(system)
    db.session.commit()
    flash("Sistema excluído.", "success")
    return redirect(url_for("systems.index"))


def clean_rest(rule, default="none"):
    """Normaliza a regra de descanso de uma barra."""
    rule = rule if isinstance(rule, dict) else {}
    mode = rule.get("mode", default)
    if mode not in dict(REST_MODES):
        mode = default
    return {"mode": mode, "value": max(0, to_int(rule.get("value"), 0))}


def _records(value):
    """Só os itens que são objetos — um JSON importado pode trazer qualquer coisa."""
    return [item for item in (value if isinstance(value, list) else []) if isinstance(item, dict)]


def formula_warnings(data):
    """Avisos das fórmulas de máximo que não funcionam com os nomes do sistema."""
    names = known_names(data)
    warnings = []
    for bar in (data or {}).get("bars") or []:
        expression = (bar.get("max_formula") or "").strip()
        if expression:
            error = validate_formula(expression, names)
            if error:
                warnings.append("Fórmula de “%s”: %s" % (bar.get("name"), error))
    return warnings


def clean_payload(payload):
    """Valida/normaliza o JSON vindo do editor ou de uma importação antes de gravar."""
    if not isinstance(payload, dict):
        payload = {}
    display = payload.get("attribute_display", "number")
    if display not in dict(DISPLAY_CHOICES):
        display = "number"
    skill_mode = payload.get("skill_mode", "bonus")
    if skill_mode not in dict(SKILL_MODE_CHOICES):
        skill_mode = "bonus"
    roll_config = payload.get("roll") if isinstance(payload.get("roll"), dict) else {}
    roll_type = roll_config.get("type", "d20_mod")
    if roll_type not in dict(ROLL_CHOICES):
        roll_type = "d20_mod"

    attributes, attr_keys = [], set()
    for item in _records(payload.get("attributes")):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = unique_key(item.get("key") or name, attr_keys)
        attr_keys.add(key)
        attributes.append(
            {
                "key": key,
                "name": name[:60],
                "abbr": (item.get("abbr") or name[:3]).strip()[:6].upper(),
                "default": to_int(item.get("default"), 0),
                "min": to_int(item.get("min"), 0),
                "max": to_int(item.get("max"), 10),
            }
        )

    bars, bar_keys = [], set()
    for item in _records(payload.get("bars")):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = unique_key(item.get("key") or name, bar_keys)
        bar_keys.add(key)
        color = clean_color(item.get("color"))
        bars.append(
            {
                "key": key,
                "rest_short": clean_rest(item.get("rest_short")),
                "rest_long": clean_rest(item.get("rest_long"), default="full"),
                "name": name[:60],
                "abbr": (item.get("abbr") or name[:3]).strip()[:6].upper(),
                "color": color,
                "default_max": to_int(item.get("default_max"), 10),
                "formula": str(item.get("formula") or "").strip()[:120],
                "max_formula": str(item.get("max_formula") or "").strip()[:160],
            }
        )

    skills, skill_keys = [], set()
    for item in _records(payload.get("skills")):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = unique_key(item.get("key") or name, skill_keys)
        skill_keys.add(key)
        attr = item.get("attr")
        if attr not in attr_keys:
            attr = attributes[0]["key"] if attributes else ""
        skills.append(
            {
                "key": key,
                "name": name[:60],
                "attr": attr,
                "default": to_int(item.get("default"), 0),
            }
        )

    metas, meta_keys = [], set()
    for item in _records(payload.get("meta_fields")):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = unique_key(item.get("key") or name, meta_keys)
        meta_keys.add(key)
        ftype = item.get("type", "text")
        if ftype not in ("text", "number", "textarea"):
            ftype = "text"
        metas.append({"key": key, "name": name[:60], "type": ftype})

    levels = []
    for item in _records(payload.get("training_levels")):
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        levels.append({"label": label[:40], "value": to_int(item.get("value"), 0)})

    inv = payload.get("inventory") if isinstance(payload.get("inventory"), dict) else {}
    inv_mode = inv.get("mode") if inv.get("mode") in dict(INVENTORY_MODES) else "none"
    capacity_attr = inv.get("capacity_attr")
    if capacity_attr not in attr_keys:
        capacity_attr = ""
    inventory = {
        "mode": inv_mode,
        "unit": (inv.get("unit") or "kg").strip()[:12] or "kg",
        "capacity_base": to_float(inv.get("capacity_base"), 0),
        "capacity_attr": capacity_attr,
        "capacity_per_point": to_float(inv.get("capacity_per_point"), 0),
        "overload_multiplier": max(1.0, to_float(inv.get("overload_multiplier"), 2.0)),
    }

    currencies, coin_keys = [], set()
    for item in _records(payload.get("currencies")):
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        key = unique_key(item.get("key") or name, coin_keys)
        coin_keys.add(key)
        currencies.append(
            {
                "key": key,
                "name": name[:40],
                "abbr": (item.get("abbr") or name[:3]).strip()[:6],
            }
        )

    raw_labels = payload.get("labels") if isinstance(payload.get("labels"), dict) else {}
    labels = {}
    for key, fallback in DEFAULT_LABELS.items():
        labels[key] = ((raw_labels.get(key) or "").strip() or fallback)[:40]

    return {
        "inventory": inventory,
        "currencies": currencies,
        "labels": labels,
        "attribute_display": display,
        "skill_mode": skill_mode,
        "roll": {
            "type": roll_type,
            "label": dict(ROLL_CHOICES)[roll_type],
            "success_on": to_int(roll_config.get("success_on"), 6),
        },
        "training_levels": levels,
        "attributes": attributes,
        "bars": bars,
        "skills": skills,
        "meta_fields": metas,
    }


# ------------------------------------------------------- exportar e importar
EXPORT_FORMAT = "grimorio-sistema"


@bp.route("/<int:system_id>/exportar")
@login_required
def export(system_id):
    """Baixa o sistema em JSON, para mandar para outro mestre."""
    system = db.get_or_404(GameSystem, system_id)
    if not system.usable_by(current_user):
        abort(403)
    body = json.dumps(
        {
            "formato": EXPORT_FORMAT,
            "versao": 1,
            "nome": system.name,
            "descricao": system.description,
            "dados": system.data or {},
        },
        ensure_ascii=False,
        indent=2,
    )
    filename = "%s.grimorio.json" % (slugify(system.name) or "sistema")
    return Response(
        body,
        mimetype="application/json",
        headers={"Content-Disposition": 'attachment; filename="%s"' % filename},
    )


@bp.route("/importar", methods=["GET", "POST"])
@login_required
def import_system():
    """Cria um sistema a partir de um JSON exportado (arquivo ou texto colado)."""
    if request.method == "POST":
        raw = ""
        upload = request.files.get("file")
        if upload is not None and upload.filename:
            raw = upload.read(512 * 1024).decode("utf-8", errors="replace")
        if not raw.strip():
            raw = request.form.get("content") or ""

        try:
            document = json.loads(raw)
        except ValueError:
            document = None

        if not isinstance(document, dict) or document.get("formato") != EXPORT_FORMAT:
            flash("Isso não parece um sistema exportado do Grimório.", "error")
            return render_template("systems/import.html", content=raw[:20000])

        data = clean_payload(document.get("dados"))
        if not data["attributes"] and not data["bars"] and not data["skills"]:
            flash("O arquivo não tem atributos, barras nem perícias.", "error")
            return render_template("systems/import.html", content=raw[:20000])

        name = str(document.get("nome") or "Sistema importado").strip()[:100]
        system = GameSystem(
            name="%s (importado)" % name,
            slug=slugify(name),
            description=str(document.get("descricao") or "").strip()[:4000],
            is_preset=False,
            owner_id=current_user.id,
            data=data,
        )
        db.session.add(system)
        db.session.commit()
        flash("Sistema importado. Confira e ajuste o que precisar.", "success")
        for warning in formula_warnings(system.data):
            flash(warning, "warning")
        return redirect(url_for("systems.detail", system_id=system.id))

    return render_template("systems/import.html", content="")
