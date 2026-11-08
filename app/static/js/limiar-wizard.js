/* Assistente de criação de Limiar.

   A página desenha as opções a partir das regras (app/limiar.py, entregues em
   JSON) e, a cada mudança, pergunta ao servidor o que está faltando. A
   conferência mora só no servidor: a mesma função decide o que esta tela mostra
   e se a ficha pode ser criada, então as duas nunca discordam.
*/
(function () {
  "use strict";

  function readJSON(id) {
    var node = document.getElementById(id);
    try { return JSON.parse(node ? node.textContent : "{}"); } catch (e) { return {}; }
  }

  var R = readJSON("limiar-rules");
  var state = readJSON("limiar-choices");
  var config = readJSON("limiar-config");
  if (!R.attributes) return;

  ["afinidades", "skills", "bencaos", "marcas", "dons"].forEach(function (k) {
    if (!Array.isArray(state[k])) state[k] = [];
  });
  state.attributes = state.attributes || {};
  R.attributes.forEach(function (a) {
    if (typeof state.attributes[a.key] !== "number") state.attributes[a.key] = 1;
  });

  var SKILL = {}; R.skills.forEach(function (s) { SKILL[s.key] = s; });
  var ESCOLA = {}; R.escolas.forEach(function (e) { ESCOLA[e.key] = e; });
  var last = { fixed_skills: [], skill_picks: 2, dons_needed: 0 };

  function $(sel, root) { return (root || document).querySelector(sel); }
  function $all(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") node.textContent = attrs[k];
      else if (k === "className") node.className = attrs[k];
      else if (attrs[k] === true) node.setAttribute(k, "");
      else if (attrs[k] !== false && attrs[k] !== null && attrs[k] !== undefined) node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) {
      if (c) node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    });
    return node;
  }

  function v24() { return state.version >= "0.24"; }
  function since(item) { return (item.since || "0.23") <= state.version; }
  function arq() {
    for (var i = 0; i < R.arquetipos.length; i++) if (R.arquetipos[i].key === state.arquetipo) return R.arquetipos[i];
    return null;
  }
  function skillNames(keys) { return keys.map(function (k) { return SKILL[k] ? SKILL[k].name : k; }).join(", "); }
  function toggle(list, key, on) {
    var i = list.indexOf(key);
    if (on && i < 0) list.push(key);
    if (!on && i >= 0) list.splice(i, 1);
  }

  /* ------------------------------------------------------------ opções */
  function card(name, type, value, checked, title, lines, onChange, disabled) {
    var input = el("input", { type: type, name: name, value: value });
    input.checked = !!checked;
    input.disabled = !!disabled;
    input.addEventListener("change", function () { onChange(input.checked); });
    var body = el("span", { className: "wz-card-body" }, [el("strong", { text: title })]);
    lines.forEach(function (line) { if (line) body.appendChild(el("span", { className: "wz-line", text: line })); });
    return el("label", { className: "wz-card" + (disabled ? " is-disabled" : "") }, [input, body]);
  }

  function renderTerra() {
    var box = $('[data-options="terra"]'); box.textContent = "";
    R.terras.forEach(function (t) {
      box.appendChild(card("terra", "radio", t.key, state.terra === t.key, t.name, [t.custom], function () {
        state.terra = t.key; changed();
      }));
    });
  }

  function renderPassado() {
    var box = $('[data-options="passado"]'); box.textContent = "";
    R.passados.filter(since).forEach(function (p) {
      box.appendChild(card("passado", "radio", p.key, state.passado === p.key, p.name,
        [skillNames(p.skills), p.ability + ": " + p.text], function () { state.passado = p.key; changed(); }));
    });
  }

  function renderArquetipo() {
    var box = $('[data-options="arquetipo"]'); box.textContent = "";
    R.arquetipos.forEach(function (a) {
      var kit = [R.weapons[a.kit.weapon].label];
      if (a.kit.armor) kit.push(R.armors[a.kit.armor].label);
      if (a.kit.shield) kit.push("escudo");
      a.kit.items.forEach(function (k) { kit.push(R.kit_items[k].name.toLowerCase()); });
      box.appendChild(card("arquetipo", "radio", a.key, state.arquetipo === a.key, a.name, [
        "PV " + a.pv_base + " + Corpo × 5 · PI " + a.pi_base + " + Alma",
        "Perícias: " + skillNames(a.skills),
        "Kit: " + kit.join(", "),
        a.n1 + ": " + a.n1_text
      ], function () {
        state.arquetipo = a.key;
        state.weapon = ""; state.armor = ""; state.shield = "";
        changed();
      }));
    });
  }

  function renderAfinidade() {
    var a = arq();
    var canal = a && a.key === "canalizador";
    $("[data-afinidade-hint]").textContent = canal
      ? "O Canalizador nasceu com várias: escolha exatamente duas escolas."
      : "Escolha uma escola, ou nenhuma. Quem nasce sem afinidade ganha 3 pontos de Bênção e não emite pulso.";
    var box = $('[data-options="afinidades"]'); box.textContent = "";
    R.escolas.forEach(function (e) {
      box.appendChild(card("afinidades", "checkbox", e.key, state.afinidades.indexOf(e.key) >= 0, e.name, [
        e.entity + " · combustível: " + e.fuel + " (" + e.price + " dr a dose)",
        "Oposta: " + ESCOLA[e.opposite].name
      ], function (on) {
        if (on && !canal) state.afinidades = [];  // fora do Canalizador, é uma só
        toggle(state.afinidades, e.key, on);
        changed();
      }));
    });
    var principalBox = $("[data-principal-box]");
    var select = $("#wz-principal");
    principalBox.hidden = state.afinidades.length < 2;
    select.textContent = "";
    select.appendChild(el("option", { value: "", text: "— escolha —" }));
    state.afinidades.forEach(function (k) {
      var opt = el("option", { value: k, text: ESCOLA[k].name });
      opt.selected = state.principal === k;
      select.appendChild(opt);
    });
  }

  function renderAttrs() {
    var box = $("[data-attrs]"); box.textContent = "";
    var total = 0;
    R.attributes.forEach(function (a) {
      var value = state.attributes[a.key];
      total += value;
      function step(delta) {
        return function () {
          state.attributes[a.key] = Math.max(0, Math.min(3, state.attributes[a.key] + delta));
          changed();
        };
      }
      var minus = el("button", { type: "button", className: "btn btn-ghost btn-sm", "aria-label": "Diminuir " + a.name, text: "−" });
      var plus = el("button", { type: "button", className: "btn btn-ghost btn-sm", "aria-label": "Aumentar " + a.name, text: "+" });
      minus.disabled = value <= 0; plus.disabled = value >= 3;
      minus.addEventListener("click", step(-1));
      plus.addEventListener("click", step(1));
      box.appendChild(el("div", { className: "wz-attr" }, [
        el("span", { className: "wz-attr-name", text: a.name }),
        minus, el("span", { className: "wz-attr-value", text: String(value) }), plus,
        el("span", { className: "wz-attr-dice muted small", text: value ? value + "d20, o maior" : "2d20, o menor" })
      ]));
    });
    var left = R.attributes.length + 4 - total;
    $("[data-attr-left]").textContent = left === 0 ? "Pontos distribuídos." :
      (left > 0 ? "Sobram " + left + "." : "Passou " + (-left) + "!");
  }

  function renderSkills() {
    var box = $("[data-skills]"); box.textContent = "";
    var fixed = last.fixed_skills;
    var passado = null;
    R.passados.forEach(function (p) { if (p.key === state.passado) passado = p; });
    var a = arq();
    // Perícia que virou "do passado" depois de marcada como livre sai da lista livre.
    state.skills = state.skills.filter(function (k) { return fixed.indexOf(k) < 0; });
    R.attributes.forEach(function (attr) {
      var group = el("div", { className: "wz-skill-group" }, [el("h3", { text: attr.name })]);
      R.skills.filter(function (s) { return s.attr === attr.key; }).forEach(function (s) {
        var from = [];
        if (passado && passado.skills.indexOf(s.key) >= 0) from.push("passado");
        if (a && a.skills.indexOf(s.key) >= 0) from.push("arquétipo");
        var input = el("input", { type: "checkbox", value: s.key });
        input.checked = from.length > 0 || state.skills.indexOf(s.key) >= 0;
        input.disabled = from.length > 0;
        input.addEventListener("change", function () { toggle(state.skills, s.key, input.checked); changed(); });
        group.appendChild(el("label", { className: "check" }, [input, " " + s.name,
          from.length ? el("span", { className: "tag", text: from.join(" e ") }) : null]));
      });
      box.appendChild(group);
    });
    var free = state.skills.length;
    $("[data-skill-picks]").textContent = last.skill_picks + " (marcadas: " + free + ")";
  }

  function renderVantagens() {
    ["bencaos", "marcas"].forEach(function (kind) {
      var box = $('[data-checks="' + kind + '"]'); box.textContent = "";
      var entity = "";
      R[kind].forEach(function (b) {
        if (b.entity !== entity) { entity = b.entity; box.appendChild(el("h4", { text: entity })); }
        var input = el("input", { type: "checkbox", value: b.key });
        input.checked = state[kind].indexOf(b.key) >= 0;
        input.addEventListener("change", function () { toggle(state[kind], b.key, input.checked); changed(); });
        box.appendChild(el("label", { className: "check wz-check" }, [input, " ",
          el("strong", { text: b.name }), el("span", { className: "tag", text: (kind === "marcas" ? "+" : "") + b.cost }),
          el("span", { className: "muted small", text: " " + b.effect })]));
      });
    });
  }

  function renderDons() {
    var section = $('[data-step="dons"]');
    var need = last.dons_needed;
    section.hidden = need === 0 && state.dons.length === 0;
    $("[data-dons-hint]").textContent = (need === 1 ? "Escolha 1 dom menor" : "Escolha " + need + " dons menores") +
      " (1 PI, DT 15)." + (v24() ? " Só das escolas das suas afinidades." : "");
    var box = $('[data-checks="dons"]'); box.textContent = "";
    var school = "";
    R.dons.filter(since).filter(function (d) {
      return !v24() || state.afinidades.indexOf(d.school) >= 0;
    }).forEach(function (d) {
      if (d.school !== school) {
        school = d.school;
        box.appendChild(el("h4", { text: ESCOLA[school].name + " · " + ESCOLA[school].entity }));
      }
      var input = el("input", { type: "checkbox", value: d.key });
      input.checked = state.dons.indexOf(d.key) >= 0;
      input.addEventListener("change", function () { toggle(state.dons, d.key, input.checked); changed(); });
      box.appendChild(el("label", { className: "check wz-check" }, [input, " ", el("strong", { text: d.name }),
        el("span", { className: "muted small", text: " (" + d.reach + ") " + d.text })]));
    });
    if (!box.childNodes.length) {
      box.appendChild(el("p", { className: "muted", text: v24() ? "Escolha a afinidade primeiro." : "Nenhum dom disponível." }));
    }
  }

  function fillSelect(select, items, current, label) {
    select.textContent = "";
    select.appendChild(el("option", { value: "", text: "— escolha —" }));
    items.forEach(function (item) {
      var opt = el("option", { value: item.key, text: label(item) });
      opt.selected = item.key === current;
      select.appendChild(opt);
    });
  }

  function renderEquipamento() {
    var a = arq();
    $("[data-weapon-box]").hidden = !a;
    $("[data-armor-box]").hidden = !(a && a.kit.armor);
    $("[data-shield-box]").hidden = !(a && a.kit.shield);
    if (!a) return;
    var parts = [R.weapons[a.kit.weapon].label + " (" + R.weapons[a.kit.weapon].damage + ")"];
    if (a.kit.armor) parts.push(R.armors[a.kit.armor].label + " (+" + R.armors[a.kit.armor].defense + " de Defesa)");
    if (a.kit.shield) parts.push("escudo (+2 de Defesa)");
    a.kit.items.forEach(function (k) { parts.push(R.kit_items[k].name.toLowerCase()); });
    if (v24() && state.afinidades.length) parts.push("um frasco de combustível de cada afinidade");
    $("[data-kit-hint]").textContent = "Kit do " + a.name + ": " + parts.join(", ") +
      ". Escolha qualquer item da categoria.";
    fillSelect($("#wz-weapon"), R.weapons[a.kit.weapon].items, state.weapon, function (w) {
      return w.name + " · " + w.type + " · " + w.props;
    });
    if (a.kit.armor) {
      fillSelect($("#wz-armor"), R.armors[a.kit.armor].items, state.armor, function (x) {
        return x.name + " · resiste " + x.resist + " · fraca " + x.weak;
      });
    }
    if (a.kit.shield) {
      fillSelect($("#wz-shield"), R.shields, state.shield, function (x) { return x.name + " · " + x.effect; });
    }
  }

  function renderSteps() {
    var n = 0;
    $all(".wz-step").forEach(function (step) {
      if (step.dataset.only) step.hidden = state.version < step.dataset.only;
      if (!step.hidden) {
        n += 1;
        var num = $(".wz-num", step);
        if (num) num.textContent = String(n);
      }
    });
  }

  function render() {
    renderTerra(); renderPassado(); renderArquetipo();
    if (v24()) renderAfinidade();
    renderAttrs(); renderSkills(); renderVantagens(); renderDons(); renderEquipamento();
    renderSteps();
  }

  /* ------------------------------------------------------------ conferência */
  var timer = null;
  var seq = 0;

  function cleanState() {
    if (!v24()) { state.afinidades = []; state.principal = ""; }
    if (state.afinidades.length < 2) state.principal = "";
    R.passados.forEach(function (p) { if (p.key === state.passado && !since(p)) state.passado = ""; });
    var allowed = R.dons.filter(since).filter(function (d) {
      return !v24() || state.afinidades.indexOf(d.school) >= 0;
    }).map(function (d) { return d.key; });
    state.dons = state.dons.filter(function (k) { return allowed.indexOf(k) >= 0; });
  }

  function changed() {
    cleanState();
    render();
    clearTimeout(timer);
    timer = setTimeout(check, 150);
  }

  function showProblems(problems) {
    var byStep = {};
    problems.forEach(function (p) { (byStep[p.step] = byStep[p.step] || []).push(p); });
    $all("[data-problems]").forEach(function (list) {
      list.textContent = "";
      (byStep[list.dataset.problems] || []).forEach(function (p) {
        list.appendChild(el("li", { className: "wz-" + p.level, text: p.msg }));
      });
    });
    $all("[data-status]").forEach(function (badge) {
      var items = byStep[badge.dataset.status] || [];
      var hasError = items.some(function (p) { return p.level === "erro"; });
      badge.className = "wz-status " + (hasError ? "is-error" : (items.length ? "is-warn" : "is-ok"));
      badge.textContent = hasError ? "falta" : (items.length ? "atenção" : "✓");
    });
    var errors = problems.filter(function (p) { return p.level === "erro"; });
    var summary = $("[data-summary-problems]"); summary.textContent = "";
    if (errors.length) {
      summary.appendChild(el("p", { className: "small", text: errors.length + (errors.length === 1 ? " pendência" : " pendências") + " antes de criar." }));
    } else {
      var warns = problems.length;
      summary.appendChild(el("p", { className: "small wz-ready", text: warns ? "Pode criar. Veja os avisos." : "Tudo certo. Pode criar." }));
    }
    $("[data-create]").disabled = errors.length > 0;
  }

  function check() {
    var mine = ++seq;
    $("#wz-choices").value = JSON.stringify(state);
    window.api(config.check_url, { body: state }).then(function (data) {
      if (mine !== seq || !data.ok) return;
      var needRender = JSON.stringify(data.fixed_skills) !== JSON.stringify(last.fixed_skills) ||
        data.skill_picks !== last.skill_picks || data.dons_needed !== last.dons_needed;
      last = data;
      if (needRender) { renderSkills(); renderDons(); renderSteps(); }
      var d = data.derived;
      var a = arq();
      $('[data-stat="pv"]').textContent = a ? d.pv : "—";
      $('[data-stat="pi"]').textContent = a ? d.pi : "—";
      $('[data-stat="defesa"]').textContent = a ? d.defesa : "—";
      $('[data-stat="carga"]').textContent = d.carga + " itens";
      var b = data.budget;
      var extra = [];
      if (b.marcas) extra.push(b.marcas + " das Marcas");
      if (b.sem_afinidade) extra.push(b.sem_afinidade + " por não ter afinidade");
      $("[data-budget]").textContent = "Gastos " + b.spent + " de " + b.total +
        (extra.length ? " (4 + " + extra.join(" + ") + ")" : "") + ".";
      $("[data-skill-picks]").textContent = data.skill_picks + " (marcadas: " + state.skills.length + ")";
      showProblems(data.problems);
    });
  }

  /* ------------------------------------------------------------ campos simples */
  $all("[data-wz]").forEach(function (input) {
    var key = input.dataset.wz;
    if (state[key] !== undefined && input.tagName !== "SELECT") input.value = state[key];
    if (key === "version") input.value = state.version || R.default_version;
    input.addEventListener(input.tagName === "SELECT" ? "change" : "input", function () {
      state[key] = input.value;
      if (input.tagName === "SELECT") changed();
      else { clearTimeout(timer); timer = setTimeout(check, 300); }
    });
  });
  state.version = state.version || R.default_version;

  $("#wz-form").addEventListener("submit", function () {
    $("#wz-choices").value = JSON.stringify(state);
  });

  changed();
})();
