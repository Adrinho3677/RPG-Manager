/* Rastreador de combate: iniciativa, turnos, vida e condições.

   Combatentes ligados a uma ficha mostram o PV e as condições da própria ficha,
   e o dano anotado aqui vai para ela. O mestre edita; os jogadores só veem, e a
   tela deles se atualiza sozinha. Inimigos chegam para os jogadores sem número
   de PV — o servidor manda só "ferido", "grave"...
*/
(function () {
  "use strict";

  var POLL_MS = 5000;
  var SAVE_DEBOUNCE_MS = 1500;

  document.querySelectorAll("[data-encounter]").forEach(function (root) {
    var editable = root.dataset.editable === "1";
    var list = root.querySelector("[data-list]");
    var roundLabel = root.querySelector("[data-round]");
    var stateLabel = root.querySelector("[data-state]");
    var messagesBox = root.querySelector("[data-messages]");
    var state;

    try {
      state = JSON.parse(root.querySelector("[data-payload]").textContent);
    } catch (e) {
      state = { combatants: [], round_number: 1, turn_index: 0 };
    }
    if (!Array.isArray(state.combatants)) state.combatants = [];

    var saving = null;
    var editedDuringSave = false;
    var pendingEdits = false;
    var saveTimer = null;

    function setStatus(text) {
      if (!stateLabel) return;
      stateLabel.textContent = text;
    }

    function showMessages(messages) {
      if (!messagesBox) return;
      if (!messages || !messages.length) return;
      messagesBox.hidden = false;
      messagesBox.innerHTML = "";
      messages.forEach(function (text) {
        var line = document.createElement("div");
        line.textContent = "⏳ " + text;
        messagesBox.appendChild(line);
      });
      clearTimeout(messagesBox._timer);
      messagesBox._timer = setTimeout(function () { messagesBox.hidden = true; }, 12000);
    }

    function el(tag, className, text) {
      var node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    }

    function field(value, onChange, attrs, readOnly) {
      var node = document.createElement("input");
      Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
      node.value = value === undefined || value === null ? "" : value;
      node.disabled = !editable;
      node.readOnly = !!readOnly;
      node.addEventListener("input", function () {
        onChange(node.value);
        edited();
      });
      return node;
    }

    function conditionsNode(c) {
      var box = el("div", "tags combat-conditions");
      (c.conditions || []).forEach(function (cond) {
        box.appendChild(el("span", "tag tag-danger",
          cond.name + (cond.rounds ? " · " + cond.rounds : "")));
      });
      return box;
    }

    function render() {
      list.innerHTML = "";
      if (!state.combatants.length) {
        list.appendChild(el("p", "muted small", "Nenhum combatente na ordem ainda."));
      }

      state.combatants.forEach(function (c, index) {
        var linked = !!c.character_id;
        var row = el("div", "combatant" + (index === state.turn_index ? " turn" : "") +
                            (linked ? " linked" : ""));

        row.appendChild(field(c.init, function (v) { c.init = v; },
          { type: "number", title: "Iniciativa", "aria-label": "Iniciativa" }));

        var nameBox = el("div", "combat-name");
        if (editable && !linked) {
          nameBox.appendChild(field(c.name, function (v) { c.name = v; },
            { type: "text", placeholder: "Nome", "aria-label": "Nome" }));
        } else {
          var title = c.sheet_url ? el("a", "", c.name) : el("strong", "", c.name);
          if (c.sheet_url) { title.href = c.sheet_url; title.target = "_blank"; }
          nameBox.appendChild(title);
          if (linked && editable) nameBox.appendChild(el("span", "tag tag-accent", "ficha"));
        }
        nameBox.appendChild(conditionsNode(c));
        row.appendChild(nameBox);

        if (c.hp !== undefined) {
          var hp = el("div", "hp-pair");
          hp.appendChild(field(c.hp, function (v) { c.hp = v; },
            { type: "number", title: "Vida atual", "aria-label": "Vida atual" }));
          hp.appendChild(el("span", "muted", "/"));
          hp.appendChild(field(c.hp_max, function (v) { c.hp_max = v; },
            { type: "number", title: linked ? "Máximo vem da ficha" : "Vida máxima",
              "aria-label": "Vida máxima" }, linked));
          row.appendChild(hp);
        } else {
          var health = c.health || "?";
          var tone = health === "caído" ? "tag-danger" : health === "grave" ? "tag-danger"
            : health === "ferido" ? "tag-gold" : "tag-ok";
          row.appendChild(el("span", "tag " + tone, health));
        }

        if (c.notes !== undefined) {
          row.appendChild(field(c.notes, function (v) { c.notes = v; },
            { type: "text", placeholder: "Notas do mestre", "aria-label": "Notas" }));
        } else {
          row.appendChild(el("span", ""));
        }

        if (editable) {
          var remove = el("button", "btn btn-danger btn-sm btn-icon", "✕");
          remove.type = "button";
          remove.title = "Tirar do combate";
          remove.addEventListener("click", function () {
            state.combatants.splice(index, 1);
            if (state.turn_index >= state.combatants.length) state.turn_index = 0;
            render();
            save();
          });
          row.appendChild(remove);
        } else {
          row.appendChild(el("span", ""));
        }
        list.appendChild(row);
      });
      roundLabel.textContent = state.round_number;
    }

    function adopt(data) {
      state = {
        name: data.name,
        round_number: data.round_number,
        turn_index: data.turn_index,
        combatants: data.combatants || []
      };
      render();
      showMessages(data.messages);
    }

    /* ------------------------------------------------------ mestre: salvar */
    function edited() {
      if (!editable) return;
      pendingEdits = true;
      if (saving) editedDuringSave = true;
      setStatus("alterações pendentes…");
      clearTimeout(saveTimer);
      saveTimer = setTimeout(save, SAVE_DEBOUNCE_MS);
    }

    function save() {
      if (!editable) return Promise.resolve();
      clearTimeout(saveTimer);
      if (saving) {
        editedDuringSave = true;
        return saving;
      }
      editedDuringSave = false;
      pendingEdits = false;
      setStatus("salvando…");
      saving = window.api(root.dataset.saveUrl, { body: state }).then(function (data) {
        saving = null;
        if (!data.ok) { setStatus(data.message || "erro ao salvar"); return; }
        if (editedDuringSave) {
          // A pessoa continuou digitando: não sobrescreve a tela, só salva de novo.
          saveTimer = setTimeout(save, 200);
          return;
        }
        adopt(data);
        setStatus("salvo ✓");
        setTimeout(function () { if (!saving) setStatus(""); }, 2500);
      }).catch(function () {
        saving = null;
        setStatus("sem conexão — tentando de novo");
        saveTimer = setTimeout(save, 4000);
      });
      return saving;
    }

    function add(body) {
      // Salva o que estiver pendente antes: a resposta substitui o estado da
      // tela, e sem isso uma edição ainda não enviada sumiria.
      var before = pendingEdits ? save() : saving;
      return Promise.resolve(before).then(function () {
        setStatus("adicionando…");
        return window.api(root.dataset.addUrl, { body: body });
      }).then(function (data) {
        if (!data.ok) { setStatus("não consegui adicionar"); return; }
        adopt(data);
        setStatus("");
      });
    }

    root.addEventListener("click", function (event) {
      var button = event.target.closest("[data-action]");
      if (!button || !root.contains(button) || !editable) return;
      var action = button.dataset.action;

      if (action === "add") {
        state.combatants.push({ name: "", init: 0, hp: 0, hp_max: 0, notes: "",
                                is_npc: true, kind: "criatura" });
        render();
      } else if (action === "add-party") {
        add({ party: true });
      } else if (action === "add-sheet") {
        var select = root.querySelector("[data-roster]");
        var quantity = root.querySelector("[data-quantity]");
        if (select && select.value) {
          add({ character_id: Number(select.value), quantity: Number(quantity.value) || 1 });
        }
      } else if (action === "next" || action === "prev") {
        if (!state.combatants.length) return;
        if (action === "next") {
          state.turn_index += 1;
          if (state.turn_index >= state.combatants.length) {
            state.turn_index = 0;
            state.round_number = Number(state.round_number || 1) + 1;
          }
        } else {
          state.turn_index -= 1;
          if (state.turn_index < 0) {
            state.turn_index = state.combatants.length - 1;
            state.round_number = Math.max(1, Number(state.round_number || 1) - 1);
          }
        }
        render();
        save();
      } else if (action === "save") {
        save();
      }
    });

    /* ------------------------------------------- jogadores: acompanhar ao vivo */
    if (!editable && root.dataset.pollUrl) {
      var poll = function () {
        if (document.hidden) return;
        window.api(root.dataset.pollUrl).then(function (data) {
          if (data.ok) adopt(data);
        }).catch(function () {});
      };
      setInterval(poll, POLL_MS);
      document.addEventListener("visibilitychange", poll);
    }

    render();
  });
})();
