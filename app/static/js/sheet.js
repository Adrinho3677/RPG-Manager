/* Ficha: abas, salvamento automático, barras e perícias ao vivo, carga e as
   listas de registros (inventário, ataques, magias, habilidades, condições,
   evolução).

   Salvamento automático
   ---------------------
   Cada mudança marca o nome do campo como "sujo". Pouco depois de a pessoa
   parar de digitar, só os campos sujos vão para o servidor, junto com a versão
   da ficha que esta tela conhece. O servidor aplica esses campos por cima do
   que está no banco — então o mestre mexendo no PV e o jogador no inventário
   não apagam um ao outro.

   Se a versão estava velha (alguém mudou a ficha), a gravação acontece mesmo
   assim e a tela entra em modo "desatualizada": continua salvando o que se
   digita, mas bloqueia os botões que enviam o formulário inteiro (descanso,
   adicionar campo), porque esses sobrescreveriam a mudança da outra pessoa.
*/
(function () {
  "use strict";

  var form = document.getElementById("sheet-form");
  if (!form) return;

  var editable = form.dataset.editable === "1";
  var config = {
    display: "number",
    skill_mode: "bonus",
    roll: { type: "d20_mod" },
    load: { mode: "none", unit: "kg", capacity: 0 },
    categories: [],
    skills: [],
    labels: {}
  };
  var configNode = document.getElementById("sheet-config");
  if (configNode) {
    try { config = Object.assign(config, JSON.parse(configNode.textContent || "{}")); } catch (e) {}
  }
  var POOL = ["pool_d10", "d6_pool"].indexOf(config.roll.type) >= 0;

  var items = { inventory: [], abilities: [], attacks: [], spells: [],
                conditions: [], progress: [] };
  var itemsNode = document.getElementById("sheet-items");
  if (itemsNode) {
    try {
      var loaded = JSON.parse(itemsNode.textContent || "{}");
      Object.keys(items).forEach(function (key) {
        if (Array.isArray(loaded[key])) items[key] = loaded[key];
      });
    } catch (e) {}
  }

  var skillState = {};

  function num(value, fallback) {
    var parsed = parseInt(value, 10);
    return isNaN(parsed) ? (fallback || 0) : parsed;
  }

  function dec(value) {
    var parsed = parseFloat(String(value === undefined || value === null ? "" : value).replace(",", "."));
    return isNaN(parsed) ? 0 : parsed;
  }

  function pretty(value) {
    var n = dec(value);
    return Math.abs(n - Math.round(n)) < 1e-9 ? String(Math.round(n)) : String(n).replace(".", ",");
  }

  function signed(value) { return value >= 0 ? "+" + value : String(value); }

  /* ================================================================ abas */
  var tabsNav = form.querySelector("[data-tabs]");
  var sections = Array.prototype.slice.call(form.querySelectorAll("[data-tab]"));
  var tabKey = "grimorio-aba-" + (config.id || "ficha");

  function showTab(name, updateHash) {
    var exists = sections.some(function (s) { return s.dataset.tab === name; });
    if (!exists) name = "combate";
    sections.forEach(function (s) { s.hidden = s.dataset.tab !== name; });
    tabsNav.querySelectorAll("[data-tab-button]").forEach(function (b) {
      var on = b.dataset.tabButton === name;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    var active = tabsNav.querySelector(".active");
    if (active && tabsNav.scrollWidth > tabsNav.clientWidth) {
      tabsNav.scrollLeft = active.offsetLeft - (tabsNav.clientWidth - active.offsetWidth) / 2;
    }
    try { sessionStorage.setItem(tabKey, name); } catch (e) {}
    if (updateHash && history.replaceState) history.replaceState(null, "", "#" + name);
  }

  if (tabsNav && sections.length) {
    // Sem JS, tudo aparece empilhado; com JS, vira abas.
    tabsNav.hidden = false;
    form.classList.add("tabs-on");
    tabsNav.addEventListener("click", function (event) {
      var button = event.target.closest("[data-tab-button]");
      if (button) showTab(button.dataset.tabButton, true);
    });
    var initial = location.hash.slice(1);
    if (!initial) { try { initial = sessionStorage.getItem(tabKey); } catch (e) {} }
    showTab(initial || "combate", false);
  }

  /* ============================================================== barras */
  function refreshBar(box) {
    var current = num(box.querySelector("[data-current]").value);
    var max = num(box.querySelector("[data-max]").value);
    var fill = box.querySelector("[data-fill]");
    var percent = max > 0 ? Math.max(0, Math.min(100, Math.round(current * 100 / max))) : 0;
    fill.style.width = percent + "%";
    fill.style.opacity = current <= 0 ? ".35" : "1";
  }

  document.querySelectorAll("[data-bar]").forEach(function (box) {
    box.addEventListener("input", function () { refreshBar(box); });
    box.querySelectorAll("[data-step]").forEach(function (button) {
      button.addEventListener("click", function () {
        var currentInput = box.querySelector("[data-current]");
        var max = num(box.querySelector("[data-max]").value);
        if (button.dataset.step === "full") {
          currentInput.value = max;
        } else {
          currentInput.value = Math.min(num(currentInput.value) + num(button.dataset.step), max);
        }
        refreshBar(box);
        markDirty(currentInput.name);
      });
    });
    refreshBar(box);
  });

  /* ================================================= atributos e perícias */
  function attrValue(key) {
    var input = form.querySelector('[data-attr="' + key + '"]');
    if (!input) return 0;
    var raw = num(input.value);
    if (config.display === "modifier") return Math.floor((raw - 10) / 2);
    return raw;
  }

  function refreshAttrLabel(input) {
    var label = form.querySelector('[data-mod-for="' + input.dataset.attr + '"]');
    if (!label) return;
    var raw = num(input.value);
    if (config.display === "modifier") {
      label.textContent = signed(Math.floor((raw - 10) / 2));
    } else if (config.display === "percent") {
      label.textContent = Math.floor(raw / 2) + " / " + Math.floor(raw / 5);
    } else if (config.display === "dots") {
      var max = num(input.getAttribute("max"), 5);
      label.textContent = "●".repeat(Math.max(0, raw)) + "○".repeat(Math.max(0, max - raw));
    }
  }

  function refreshSkill(row) {
    var attr = attrValue(row.dataset.attr);
    var other = num(row.querySelector("[data-other]").value);
    var totalNode = row.querySelector("[data-total]");
    var rollButton = row.querySelector("[data-roll]");
    var total, dice = 1, text;

    if (config.skill_mode === "training") {
      var train = num((row.querySelector("[data-train]") || {}).value);
      if (config.roll.type === "keep_highest_d20") {
        total = train + other;
        dice = Math.max(0, attr);
        text = (dice || 2) + "d+" + total;
      } else {
        total = attr + train + other;
        text = signed(total);
      }
    } else if (config.skill_mode === "proficiency") {
      var prof = num((row.querySelector("[data-prof]") || {}).value);
      var profBonus = num((form.querySelector('[name="meta__prof"]') || {}).value, 2);
      total = attr + prof * profBonus + other;
      text = signed(total);
    } else if (config.skill_mode === "percent") {
      total = num((row.querySelector("[data-value]") || {}).value) + other;
      text = total + "%";
    } else if (config.skill_mode === "dots") {
      total = attr + num((row.querySelector("[data-value]") || {}).value) + other;
      dice = total;
      text = total + "d";
    } else {
      total = attr + num((row.querySelector("[data-value]") || {}).value) + other;
      text = signed(total);
    }

    totalNode.textContent = text;
    skillState[row.dataset.skill] = { total: total, dice: dice };
    if (rollButton) {
      rollButton.dataset.dice = dice;
      // Nas paradas, o total já é a quantidade de dados; mandar também como
      // bônus dobrava a parada.
      rollButton.dataset.bonus = POOL ? 0 : total;
      rollButton.dataset.target = total;
    }
  }

  function refreshAllSkills() {
    document.querySelectorAll("[data-skill]").forEach(refreshSkill);
  }

  form.querySelectorAll("[data-attr]").forEach(function (input) {
    input.addEventListener("input", function () {
      refreshAttrLabel(input);
      refreshAllSkills();
      refreshLoad();
      var rollButton = input.closest(".attr").querySelector("[data-roll]");
      if (rollButton) {
        var value = attrValue(input.dataset.attr);
        var byAttr = POOL || config.roll.type === "keep_highest_d20";
        rollButton.dataset.dice = byAttr ? value : 1;
        rollButton.dataset.bonus = byAttr ? 0 : value;
        rollButton.dataset.target = num(input.value);
      }
    });
  });

  document.querySelectorAll("[data-skill]").forEach(function (row) {
    row.addEventListener("input", function () { refreshSkill(row); });
    row.addEventListener("change", function () { refreshSkill(row); });
  });

  /* =============================================================== carga */
  var loadBox = document.querySelector("[data-load]");

  function refreshLoad() {
    if (!loadBox) return;
    var used = 0;
    items.inventory.forEach(function (item) {
      used += dec(item.weight) * Math.max(0, num(item.qty, 1));
    });

    var capacity = dec(loadBox.dataset.capacity);
    var attrInput = config.load.attr ? form.querySelector('[data-attr="' + config.load.attr + '"]') : null;
    if (attrInput) {
      capacity = dec(config.load.base) + num(attrInput.value) * dec(config.load.per_point);
    }
    var overload = dec(config.load.overload) || 2;

    var fill = loadBox.querySelector("[data-load-fill]");
    var percent = capacity > 0 ? Math.max(0, Math.min(100, Math.round(used * 100 / capacity))) : 0;
    fill.style.width = percent + "%";

    var state = "ok";
    if (capacity > 0 && used > capacity * overload) state = "over";
    else if (capacity > 0 && used > capacity) state = "warn";

    fill.style.background = state === "over" ? "var(--danger)"
      : state === "warn" ? "var(--accent-2)" : "var(--success)";
    var tag = document.querySelector("[data-load-tag]");
    if (tag) {
      tag.textContent = state === "over" ? "Acima do limite"
        : state === "warn" ? "Sobrecarregado" : "Dentro do limite";
      tag.className = "tag " + (state === "over" ? "tag-danger" : state === "warn" ? "tag-gold" : "tag-ok");
    }
    loadBox.querySelector("[data-load-used]").textContent = pretty(used);
    var capNode = loadBox.querySelector("[data-load-capacity]");
    if (capNode) capNode.textContent = pretty(capacity);
  }

  /* ============================================ listas genéricas da ficha */
  function skillOptions() {
    return config.skills.map(function (s) { return [s.key, s.name]; });
  }

  var unitLabel = config.load.unit || "kg";
  var GROUPS = {
    inventory: {
      empty: "Mochila vazia.",
      fields: function () {
        var fields = [{ k: "name", t: "text", label: "Item", grow: 3 },
                      { k: "qty", t: "number", label: "Qtd", grow: 0 }];
        if (config.load.mode !== "none") {
          fields.push({ k: "weight", t: "decimal", label: unitLabel, grow: 0 });
        }
        fields.push({ k: "category", t: "select", label: "Tipo", grow: 1,
                      options: config.categories.map(function (c) { return [c, c]; }) });
        fields.push({ k: "value", t: "number", label: "Valor", grow: 0 });
        fields.push({ k: "equipped", t: "check", label: "Equipado", grow: 0 });
        fields.push({ k: "desc", t: "textarea", label: "Detalhes", full: true });
        return fields;
      }
    },
    abilities: {
      empty: "Nada anotado ainda.",
      fields: function () {
        return [{ k: "name", t: "text", label: "Nome", grow: 3 },
                { k: "desc", t: "textarea", label: "Descrição", full: true }];
      }
    },
    attacks: {
      empty: "Nenhum ataque cadastrado.",
      roll: "attack",
      fields: function () {
        return [{ k: "name", t: "text", label: "Nome", grow: 3 },
                { k: "test", t: "select", label: "Teste", grow: 2, options: skillOptions(), blank: "— nenhum —" },
                { k: "bonus", t: "number", label: POOL ? "Dados extras" : "Bônus extra", grow: 0 },
                { k: "damage", t: "text", label: "Dano", grow: 1, ph: "1d8+3" },
                { k: "crit", t: "text", label: "Crítico", grow: 0, ph: "19/x2" },
                { k: "range", t: "text", label: "Alcance", grow: 1, ph: "Corpo a corpo" },
                { k: "desc", t: "textarea", label: "Observações", full: true }];
      }
    },
    spells: {
      empty: "Nenhuma entrada ainda.",
      fields: function () {
        return [{ k: "name", t: "text", label: "Nome", grow: 3 },
                { k: "level", t: "number", label: config.labels.spell_level || "Círculo", grow: 0 },
                { k: "cost", t: "text", label: "Custo", grow: 0, ph: "2 PE" },
                { k: "execution", t: "text", label: "Execução", grow: 1, ph: "Padrão" },
                { k: "range", t: "text", label: "Alcance", grow: 1, ph: "Curto" },
                { k: "duration", t: "text", label: "Duração", grow: 1, ph: "Instantânea" },
                { k: "prepared", t: "check", label: "Preparada", grow: 0 },
                { k: "desc", t: "textarea", label: "Efeito", full: true }];
      }
    },
    progress: {
      empty: "Nada registrado ainda.",
      compact: true,
      fields: function () {
        return [{ k: "at", t: "text", label: "Quando", grow: 0, ph: "2026-09-15" },
                { k: "name", t: "text", label: "O que aconteceu", grow: 3 },
                { k: "amount", t: "number", label: "XP", grow: 0 },
                { k: "desc", t: "text", label: "Detalhes", grow: 2 }];
      }
    },
    conditions: {
      empty: "Nenhuma condição ativa.",
      compact: true,
      fields: function () {
        return [{ k: "name", t: "text", label: "Condição", grow: 2 },
                { k: "rounds", t: "number", label: "Rodadas", grow: 0 },
                { k: "desc", t: "text", label: "Efeito", grow: 3 }];
      }
    }
  };

  function makeField(spec, record, group) {
    var wrap = document.createElement("div");
    wrap.className = "record-field" + (spec.full ? " full" : "");
    if (spec.grow === 0) wrap.classList.add("tight");
    else if (spec.grow >= 3) wrap.classList.add("wide");
    else if (spec.grow === 2) wrap.classList.add("mid");

    var label = document.createElement("label");
    label.textContent = spec.label;
    wrap.appendChild(label);

    var node;
    if (spec.t === "select") {
      node = document.createElement("select");
      if (spec.blank) {
        var blank = document.createElement("option");
        blank.value = "";
        blank.textContent = spec.blank;
        node.appendChild(blank);
      }
      (spec.options || []).forEach(function (pair) {
        var option = document.createElement("option");
        option.value = pair[0];
        option.textContent = pair[1];
        if (String(record[spec.k] || "") === String(pair[0])) option.selected = true;
        node.appendChild(option);
      });
    } else if (spec.t === "textarea") {
      node = document.createElement("textarea");
      node.style.minHeight = "52px";
      node.value = record[spec.k] || "";
    } else if (spec.t === "check") {
      node = document.createElement("input");
      node.type = "checkbox";
      node.checked = !!record[spec.k];
      wrap.classList.add("check-field");
    } else {
      node = document.createElement("input");
      if (spec.t === "decimal") {
        // input[type=number] rejeita "3,5"; aqui o jogador pode usar vírgula ou ponto.
        node.type = "text";
        node.inputMode = "decimal";
      } else {
        node.type = spec.t;
        if (spec.t === "number") node.min = "0";
      }
      node.value = record[spec.k] === undefined || record[spec.k] === null ? "" : record[spec.k];
    }

    if (spec.ph) node.placeholder = spec.ph;
    node.disabled = !editable;
    node.dataset.listField = "1";  // não é campo do formulário; quem salva é o JSON escondido

    function update() {
      record[spec.k] = spec.t === "check" ? node.checked : node.value;
      sync(group, true);
      if (group === "inventory" && (spec.k === "weight" || spec.k === "qty")) refreshLoad();
      if (group === "conditions") renderHeaderConditions();
    }
    node.addEventListener(spec.t === "select" || spec.t === "check" ? "change" : "input", update);

    wrap.appendChild(node);
    return wrap;
  }

  function renderGroup(group, fromUser) {
    var container = document.getElementById(group + "-rows");
    var hidden = document.getElementById(group + "-input");
    if (!container || !hidden) return;
    var spec = GROUPS[group];
    container.innerHTML = "";

    if (!items[group].length) {
      var empty = document.createElement("p");
      empty.className = "muted small";
      empty.textContent = spec.empty;
      container.appendChild(empty);
    }

    items[group].forEach(function (record, index) {
      var card = document.createElement("div");
      card.className = "record" + (spec.compact ? " record-compact" : "") +
        (record.equipped ? " equipped" : "");

      var grid = document.createElement("div");
      grid.className = "record-grid";
      spec.fields().forEach(function (fieldSpec) {
        grid.appendChild(makeField(fieldSpec, record, group));
      });
      card.appendChild(grid);

      var actions = document.createElement("div");
      actions.className = "record-actions";

      if (spec.roll === "attack" && editable) {
        var testBtn = document.createElement("button");
        testBtn.type = "button";
        testBtn.className = "btn btn-ghost btn-sm";
        testBtn.textContent = "🎲 Testar";
        testBtn.dataset.attackTest = index;
        actions.appendChild(testBtn);

        var dmgBtn = document.createElement("button");
        dmgBtn.type = "button";
        dmgBtn.className = "btn btn-gold btn-sm";
        dmgBtn.textContent = "🎲 Dano";
        dmgBtn.dataset.attackDamage = index;
        actions.appendChild(dmgBtn);
      }

      if (editable) {
        var remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn btn-danger btn-sm btn-icon";
        remove.textContent = "✕";
        remove.title = "Remover";
        remove.addEventListener("click", function () {
          items[group].splice(index, 1);
          renderGroup(group, true);
          if (group === "inventory") refreshLoad();
        });
        actions.appendChild(remove);
      }

      if (actions.children.length) card.appendChild(actions);
      container.appendChild(card);
    });

    sync(group, fromUser);
    if (group === "conditions") renderHeaderConditions();
  }

  function sync(group, fromUser) {
    var hidden = document.getElementById(group + "-input");
    if (!hidden) return;
    hidden.value = JSON.stringify(items[group]);
    if (fromUser) markDirty(hidden.name);
  }

  function renderHeaderConditions() {
    var box = document.querySelector("[data-header-conditions]");
    if (!box) return;
    box.innerHTML = "";
    items.conditions.forEach(function (c) {
      if (!c.name) return;
      var tag = document.createElement("span");
      tag.className = "tag tag-danger";
      tag.textContent = c.name + (num(c.rounds) ? " · " + num(c.rounds) + " rod." : "");
      box.appendChild(tag);
    });
  }

  document.addEventListener("click", function (event) {
    var test = event.target.closest("[data-attack-test]");
    if (test) {
      var attack = items.attacks[Number(test.dataset.attackTest)];
      if (!attack) return;
      var skill = skillState[attack.test] || { total: 0, dice: 1 };
      var extra = num(attack.bonus);
      // Paradas: bônus do ataque são dados a mais. Demais sistemas: soma no total.
      var bonus = POOL ? extra : skill.total + extra;
      window.Dice.roll(attack.name || "Ataque", skill.dice, bonus, skill.total + extra);
      return;
    }
    var damage = event.target.closest("[data-attack-damage]");
    if (damage) {
      var item = items.attacks[Number(damage.dataset.attackDamage)];
      if (item) window.Dice.formula(item.damage || "", "Dano · " + (item.name || "ataque"));
    }
  });

  var BLANKS = {
    inventory: function () {
      return { name: "", qty: 1, weight: 0, category: "geral", value: 0, equipped: false, desc: "" };
    },
    abilities: function () { return { name: "", desc: "" }; },
    attacks: function () {
      return { name: "", test: "", bonus: 0, damage: "", crit: "", range: "", desc: "" };
    },
    spells: function () {
      return { name: "", level: 1, cost: "", execution: "", range: "", duration: "",
               prepared: false, desc: "" };
    },
    conditions: function () { return { name: "", rounds: 0, desc: "" }; },
    progress: function () {
      return { at: new Date().toISOString().slice(0, 10), name: "", amount: 0, desc: "" };
    }
  };

  document.querySelectorAll("[data-add-item]").forEach(function (button) {
    button.addEventListener("click", function () {
      var group = button.dataset.addItem;
      items[group].push(BLANKS[group]());
      renderGroup(group, false);  // item vazio não é salvo até ganhar nome
    });
  });

  document.querySelectorAll("[data-quick-condition]").forEach(function (button) {
    button.addEventListener("click", function () {
      var name = button.dataset.quickCondition;
      var existing = items.conditions.findIndex(function (c) { return c.name === name; });
      if (existing >= 0) items.conditions.splice(existing, 1);
      else items.conditions.push({ name: name, rounds: 0, desc: "" });
      renderGroup("conditions", true);
    });
  });

  /* =================================================== salvamento automático */
  var versionInput = form.querySelector("[data-version]");
  var stateLabel = document.querySelector("[data-save-state]");
  var staleBanner = document.querySelector("[data-stale-banner]");
  var dirty = {};
  var saving = null;         // Promise da gravação em andamento
  var timer = null;
  var stale = false;
  var submitting = false;
  var DEBOUNCE_MS = 1200;

  function dirtyCount() { return Object.keys(dirty).length; }

  function setState(text, kind) {
    if (!stateLabel) return;
    stateLabel.textContent = text;
    stateLabel.dataset.kind = kind || "";
  }

  function ignored(name) {
    return !name || name === "csrf_token" || name === "version" || name === "__action" ||
      name.indexOf("new_") === 0;
  }

  function markDirty(name) {
    if (!editable || ignored(name)) return;
    dirty[name] = true;
    setState("Alterações pendentes…", "pending");
    clearTimeout(timer);
    timer = setTimeout(flush, DEBOUNCE_MS);
  }

  function lockStale() {
    if (stale) return;
    stale = true;
    if (staleBanner) staleBanner.hidden = false;
  }

  function applyServer(data) {
    Object.keys(data.bars || {}).forEach(function (key) {
      var box = form.querySelector('[data-bar="' + key + '"]');
      if (!box) return;
      var info = data.bars[key];
      var maxInput = box.querySelector("[data-max]");
      var currentInput = box.querySelector("[data-current]");
      // Máximo calculado por fórmula e valor atual limitado: vêm do servidor,
      // mas não mexemos num campo que a pessoa está digitando agora.
      if (info.auto && document.activeElement !== maxInput) maxInput.value = info.max;
      if (document.activeElement !== currentInput && !dirty[currentInput.name]) {
        currentInput.value = info.current;
      }
      var error = box.querySelector("[data-formula-error]");
      if (error) {
        error.hidden = !info.error;
        error.textContent = info.error ? "⚠️ " + info.error : "";
      }
      refreshBar(box);
    });
  }

  function flush(options) {
    options = options || {};
    if (saving) {
      // Uma gravação por vez: a próxima sai quando esta terminar.
      return saving.then(function () { return dirtyCount() ? flush(options) : null; });
    }
    if (!dirtyCount()) return Promise.resolve();
    clearTimeout(timer);

    var names = Object.keys(dirty);
    dirty = {};
    var body = new FormData();
    body.append("version", versionInput.value);
    names.forEach(function (name) {
      var field = form.elements[name];
      if (field) body.append(name, field.value);
    });

    setState("Salvando…", "saving");
    saving = window.api(location.pathname, { body: body, keepalive: options.keepalive })
      .then(function (data) {
        saving = null;
        if (!data.ok) {
          names.forEach(function (n) { dirty[n] = true; });
          setState(data.message || "Não consegui salvar. Tento de novo em instantes.", "error");
          timer = setTimeout(flush, 5000);
          return;
        }
        if (data.stale) {
          lockStale();  // mantém a versão velha: envios completos ficam recusados
        } else if (!stale) {
          versionInput.value = data.version;
        }
        applyServer(data);
        var hora = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
        setState(stale ? "Salvo às " + hora + " · ficha desatualizada" : "Salvo às " + hora, "saved");
        if (dirtyCount()) timer = setTimeout(flush, 300);
      })
      .catch(function () {
        saving = null;
        names.forEach(function (n) { dirty[n] = true; });
        setState("Sem conexão. Tento de novo em instantes.", "error");
        timer = setTimeout(flush, 5000);
      });
    return saving;
  }

  if (editable) {
    form.addEventListener("input", function (event) {
      if (event.target.dataset.listField) return;
      markDirty(event.target.name);
    });
    form.addEventListener("change", function (event) {
      if (event.target.dataset.listField) return;
      markDirty(event.target.name);
    });

    // Enter num campo de texto não pode enviar o formulário: o "primeiro botão"
    // é o de descanso, e um Enter distraído descansava o personagem.
    form.addEventListener("keydown", function (event) {
      if (event.key !== "Enter") return;
      var target = event.target;
      if (target.tagName === "INPUT" && ["checkbox", "radio", "submit", "button"].indexOf(target.type) < 0) {
        event.preventDefault();
        flush();
      }
    });

    // Navegadores antigos (Safari < 15.4) não têm event.submitter.
    var lastSubmitter = null;
    form.addEventListener("click", function (event) {
      var button = event.target.closest && event.target.closest("button[type=submit], input[type=submit]");
      if (button) lastSubmitter = button;
    });

    // Envios completos (descanso, adicionar campo, "Salvar agora"): primeiro
    // termina o salvamento automático, para a versão enviada estar em dia.
    form.addEventListener("submit", function (event) {
      if (submitting) return;
      if (!stale && !saving && !dirtyCount()) {
        // Nada pendente: deixa o navegador enviar normalmente, com o botão
        // clicado (o __action) e tudo — sem interceptar nem reenviar.
        clearTimeout(timer);
        submitting = true;
        return;
      }
      event.preventDefault();
      var submitter = event.submitter || lastSubmitter;
      if (stale) {
        if (staleBanner) {
          staleBanner.hidden = false;
          staleBanner.classList.remove("shake");
          void staleBanner.offsetWidth;
          staleBanner.classList.add("shake");
        }
        return;
      }
      setState("Salvando…", "saving");
      Promise.resolve(flush()).then(function () {
        if (stale) {
          setState("Ficha desatualizada — recarregue antes de continuar.", "error");
          return;
        }
        submitting = true;
        // form.submit() não dispara eventos nem é ignorado pelo navegador (o
        // requestSubmit às vezes era, e a ficha ficava em "Salvando…"), mas
        // também não leva o botão clicado: o __action vai num campo oculto.
        if (submitter && submitter.name) {
          var hidden = document.createElement("input");
          hidden.type = "hidden";
          hidden.name = submitter.name;
          hidden.value = submitter.value;
          form.appendChild(hidden);
        }
        setTimeout(function () { form.submit(); }, 0);
      });
    });

    // Desfazer e afins: terminam o salvamento pendente antes, senão ele chegaria
    // depois e reaplicaria justamente o que se quis desfazer.
    document.querySelectorAll("form[data-flush-first]").forEach(function (other) {
      other.addEventListener("submit", function (event) {
        if (other.dataset.flushed) return;
        if (event.defaultPrevented) return;  // o confirm() foi cancelado
        event.preventDefault();
        clearTimeout(timer);
        Promise.resolve(flush()).then(function () {
          dirty = {};
          submitting = true;
          other.dataset.flushed = "1";
          other.submit();
        });
      });
    });

    var reload = document.querySelector("[data-reload]");
    if (reload) {
      reload.addEventListener("click", function () {
        Promise.resolve(flush()).then(function () {
          dirty = {};
          submitting = true;  // não perguntar "sair da página?"
          location.reload();
        });
      });
    }

    document.addEventListener("visibilitychange", function () {
      if (document.hidden && dirtyCount()) flush({ keepalive: true });
    });

    window.addEventListener("beforeunload", function (event) {
      if (submitting || (!dirtyCount() && !saving)) return;
      flush({ keepalive: true });
      event.preventDefault();
      event.returnValue = "";
    });

    /* Percebe mudanças feitas por outra pessoa sem esperar o próximo salvamento. */
    function checkForChanges() {
      if (document.hidden || saving || stale || !config.state_url) return;
      window.api(config.state_url).then(function (data) {
        if (saving || stale || !data.ok) return;
        if (Number(data.version) > Number(versionInput.value)) lockStale();
      }).catch(function () {});
    }
    if (window.Live && window.Live.enabled && config.id) {
      // Ficha de campanha: a versão vem junto com as rolagens da mesa.
      window.Live.register("sheet", config.id, function (data) {
        if (saving || stale) return;
        if (Number(data.version) > Number(versionInput.value)) lockStale();
      }, { mark: versionInput.value });
    } else {
      setInterval(checkForChanges, 20000);
      document.addEventListener("visibilitychange", function () {
        if (!document.hidden) checkForChanges();
      });
    }
  }

  Object.keys(GROUPS).forEach(function (group) { renderGroup(group, false); });
  refreshAllSkills();
  refreshLoad();
})();
