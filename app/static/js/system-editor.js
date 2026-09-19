/* Editor de sistema: monta as linhas das tabelas e serializa tudo em JSON. */
(function () {
  "use strict";

  var raw = document.getElementById("system-data");
  var state = {};
  try { state = JSON.parse(raw.textContent || "{}"); } catch (e) { state = {}; }

  ["attributes", "bars", "skills", "meta_fields", "training_levels", "currencies"]
    .forEach(function (key) {
      if (!Array.isArray(state[key])) state[key] = [];
    });
  if (!state.inventory || typeof state.inventory !== "object") state.inventory = {};
  if (!state.labels || typeof state.labels !== "object") state.labels = {};

  var form = document.getElementById("system-form");
  var payload = document.getElementById("payload");
  var displaySel = document.getElementById("attribute_display");
  var skillModeSel = document.getElementById("skill_mode");
  var rollSel = document.getElementById("roll_type");
  var invMode = document.getElementById("inv_mode");
  var invUnit = document.getElementById("inv_unit");
  var invBase = document.getElementById("inv_base");
  var invAttr = document.getElementById("inv_attr");
  var invPer = document.getElementById("inv_per");
  var invOver = document.getElementById("inv_over");
  var invPreview = document.getElementById("inv-preview");

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "class") node.className = attrs[k];
      else if (k === "text") node.textContent = attrs[k];
      else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { node.appendChild(c); });
    return node;
  }

  function input(type, value, onChange, extra) {
    var node = el("input", Object.assign({ type: type }, extra || {}));
    node.value = value === undefined || value === null ? "" : value;
    node.addEventListener("input", function () { onChange(node.value); });
    return node;
  }

  function cell(child) { return el("td", {}, [child]); }

  function removeButton(group, index) {
    var btn = el("button", { type: "button", class: "btn btn-danger btn-sm", text: "Remover" });
    btn.addEventListener("click", function () {
      state[group].splice(index, 1);
      renderAll();
    });
    return btn;
  }

  function moveButton(group, index, delta, label) {
    var btn = el("button", { type: "button", class: "btn btn-ghost btn-sm btn-icon", text: label });
    btn.addEventListener("click", function () {
      var target = index + delta;
      if (target < 0 || target >= state[group].length) return;
      var items = state[group];
      var tmp = items[index];
      items[index] = items[target];
      items[target] = tmp;
      renderAll();
    });
    return btn;
  }

  function toolCell(group, index) {
    return el("td", { class: "nowrap" }, [
      moveButton(group, index, -1, "↑"),
      moveButton(group, index, 1, "↓"),
      removeButton(group, index)
    ]);
  }

  function attributeOptions(selected) {
    var select = el("select", {});
    state.attributes.forEach(function (attr) {
      var option = el("option", { value: attr.key || attr.name, text: attr.name || "(sem nome)" });
      if ((attr.key || attr.name) === selected) option.selected = true;
      select.appendChild(option);
    });
    if (!state.attributes.length) {
      select.appendChild(el("option", { value: "", text: "— crie um atributo primeiro —" }));
    }
    return select;
  }

  function renderAttributes() {
    var body = document.getElementById("rows-attributes");
    body.innerHTML = "";
    state.attributes.forEach(function (item, index) {
      var row = el("tr", {}, [
        cell(input("text", item.name, function (v) { item.name = v; }, { placeholder: "Agilidade" })),
        cell(input("text", item.abbr, function (v) { item.abbr = v; }, { maxlength: "6", placeholder: "AGI" })),
        cell(input("number", item.default, function (v) { item.default = v; })),
        cell(input("number", item.min, function (v) { item.min = v; })),
        cell(input("number", item.max, function (v) { item.max = v; })),
        toolCell("attributes", index)
      ]);
      body.appendChild(row);
    });
  }

  var REST_MODES = [
    ["none", "Não recupera"],
    ["full", "Recupera tudo"],
    ["half", "Metade do máximo"],
    ["amount", "Soma X pontos"],
    ["percent", "Soma X% do máximo"]
  ];

  function restCell(item, kind) {
    var field = "rest_" + kind;
    if (!item[field] || typeof item[field] !== "object") {
      item[field] = { mode: kind === "long" ? "full" : "none", value: 0 };
    }
    var rule = item[field];

    var wrap = el("div", { class: "rest-cell" });
    var select = el("select", {});
    REST_MODES.forEach(function (pair) {
      var option = el("option", { value: pair[0], text: pair[1] });
      if (rule.mode === pair[0]) option.selected = true;
      select.appendChild(option);
    });
    var amount = input("number", rule.value, function (v) { rule.value = v; }, { min: "0" });

    function toggleAmount() {
      amount.style.display = (rule.mode === "amount" || rule.mode === "percent") ? "" : "none";
    }
    select.addEventListener("change", function () {
      rule.mode = select.value;
      toggleAmount();
      serialize();
    });
    toggleAmount();

    wrap.appendChild(select);
    wrap.appendChild(amount);
    return el("td", {}, [wrap]);
  }

  function renderBars() {
    var body = document.getElementById("rows-bars");
    body.innerHTML = "";
    state.bars.forEach(function (item, index) {
      body.appendChild(el("tr", {}, [
        cell(input("text", item.name, function (v) { item.name = v; }, { placeholder: "Pontos de Vida" })),
        cell(input("text", item.abbr, function (v) { item.abbr = v; }, { maxlength: "6", placeholder: "PV" })),
        cell(input("number", item.default_max, function (v) { item.default_max = v; })),
        cell(input("color", item.color || "#c0392b", function (v) { item.color = v; }, { style: "padding:2px;height:34px" })),
        cell(input("text", item.max_formula, function (v) { item.max_formula = v; }, { placeholder: "opcional: 20 + VIG * 4" })),
        cell(input("text", item.formula, function (v) { item.formula = v; }, { placeholder: "texto livre" })),
        restCell(item, "short"),
        restCell(item, "long"),
        toolCell("bars", index)
      ]));
    });
  }

  function renderSkills() {
    var body = document.getElementById("rows-skills");
    body.innerHTML = "";
    state.skills.forEach(function (item, index) {
      var select = attributeOptions(item.attr);
      select.addEventListener("change", function () { item.attr = select.value; });
      body.appendChild(el("tr", {}, [
        cell(input("text", item.name, function (v) { item.name = v; }, { placeholder: "Percepção" })),
        cell(select),
        cell(input("number", item.default, function (v) { item.default = v; })),
        toolCell("skills", index)
      ]));
    });
  }

  function renderMeta() {
    var body = document.getElementById("rows-meta_fields");
    body.innerHTML = "";
    state.meta_fields.forEach(function (item, index) {
      var select = el("select", {});
      [["text", "Texto"], ["number", "Número"], ["textarea", "Texto longo"]].forEach(function (pair) {
        var option = el("option", { value: pair[0], text: pair[1] });
        if (item.type === pair[0]) option.selected = true;
        select.appendChild(option);
      });
      select.addEventListener("change", function () { item.type = select.value; });
      body.appendChild(el("tr", {}, [
        cell(input("text", item.name, function (v) { item.name = v; }, { placeholder: "Classe" })),
        cell(select),
        toolCell("meta_fields", index)
      ]));
    });
  }

  function renderTraining() {
    var body = document.getElementById("rows-training_levels");
    body.innerHTML = "";
    state.training_levels.forEach(function (item, index) {
      body.appendChild(el("tr", {}, [
        cell(input("text", item.label, function (v) { item.label = v; }, { placeholder: "Treinado" })),
        cell(input("number", item.value, function (v) { item.value = v; })),
        toolCell("training_levels", index)
      ]));
    });
    document.getElementById("training-card").style.display =
      skillModeSel.value === "training" ? "" : "none";
  }

  function renderCurrencies() {
    var body = document.getElementById("rows-currencies");
    body.innerHTML = "";
    state.currencies.forEach(function (item, index) {
      body.appendChild(el("tr", {}, [
        cell(input("text", item.name, function (v) { item.name = v; }, { placeholder: "Tibares" })),
        cell(input("text", item.abbr, function (v) { item.abbr = v; }, { maxlength: "6", placeholder: "T$" })),
        toolCell("currencies", index)
      ]));
    });
  }

  function renderInventory() {
    var current = state.inventory.capacity_attr || "";
    invAttr.innerHTML = "";
    invAttr.appendChild(el("option", { value: "", text: "— nenhum —" }));
    state.attributes.forEach(function (attr) {
      var key = attr.key || attr.name;
      var option = el("option", { value: key, text: attr.name || "(sem nome)" });
      if (key === current) option.selected = true;
      invAttr.appendChild(option);
    });

    var usesCapacity = invMode.value !== "none";
    document.getElementById("inv-capacity").style.display = usesCapacity ? "" : "none";
    if (!usesCapacity) {
      invPreview.textContent = "A ficha não mostra barra de carga neste modo.";
      return;
    }
    var attrName = invAttr.selectedIndex > 0 ? invAttr.options[invAttr.selectedIndex].text : null;
    invPreview.textContent = "Capacidade = " + (Number(invBase.value) || 0) +
      (attrName ? " + " + attrName + " × " + (Number(invPer.value) || 0) : "") +
      " " + (invUnit.value || "kg") + ". Acima disso o personagem fica sobrecarregado.";
  }

  function serialize() {
    state.attribute_display = displaySel.value;
    state.skill_mode = skillModeSel.value;
    state.roll = Object.assign({}, state.roll || {}, { type: rollSel.value });
    var initSource = document.getElementById("init_source");
    if (initSource) {
      var initValue = document.getElementById("init_value").value.trim();
      state.initiative = { source: initSource.value, roll: document.getElementById("init_roll").checked };
      if (initSource.value === "formula") state.initiative.formula = initValue;
      else state.initiative.key = initValue;
    }
    state.inventory = {
      mode: invMode.value,
      unit: invUnit.value,
      capacity_base: Number(invBase.value) || 0,
      capacity_attr: invAttr.value,
      capacity_per_point: Number(invPer.value) || 0,
      overload_multiplier: Number(invOver.value) || 2
    };
    document.querySelectorAll("[data-label-key]").forEach(function (node) {
      state.labels[node.dataset.labelKey] = node.value;
    });
    payload.value = JSON.stringify(state);
  }

  function renderAll() {
    renderAttributes();
    renderBars();
    renderSkills();
    renderMeta();
    renderTraining();
    renderCurrencies();
    renderInventory();
    serialize();
  }

  var blanks = {
    attributes: function () { return { name: "", abbr: "", default: 0, min: 0, max: 10 }; },
    bars: function () {
      return { name: "", abbr: "", default_max: 10, color: "#c0392b", formula: "", max_formula: "",
               rest_short: { mode: "none", value: 0 }, rest_long: { mode: "full", value: 0 } };
    },
    skills: function () {
      return { name: "", attr: state.attributes.length ? state.attributes[0].key : "", default: 0 };
    },
    meta_fields: function () { return { name: "", type: "text" }; },
    training_levels: function () { return { label: "", value: 0 }; },
    currencies: function () { return { name: "", abbr: "" }; }
  };

  document.querySelectorAll("[data-add]").forEach(function (button) {
    button.addEventListener("click", function () {
      var group = button.getAttribute("data-add");
      state[group].push(blanks[group]());
      renderAll();
    });
  });

  skillModeSel.addEventListener("change", function () {
    renderTraining();
    serialize();
  });
  displaySel.addEventListener("change", serialize);
  rollSel.addEventListener("change", serialize);
  [invMode, invUnit, invBase, invAttr, invPer, invOver].forEach(function (node) {
    // serialize primeiro: renderInventory reconstrói o <select> a partir do
    // estado, e rodar antes apagaria o valor que o usuário acabou de escolher.
    function onChange() { serialize(); renderInventory(); }
    node.addEventListener("change", onChange);
    node.addEventListener("input", onChange);
  });

  // Mantém o campo escondido sempre atualizado — inclusive se o envio
  // acontecer sem passar pelo evento de submit.
  form.addEventListener("input", serialize);
  form.addEventListener("change", serialize);
  form.addEventListener("submit", serialize);

  renderAll();
})();
