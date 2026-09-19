/* Rolador de dados.

   Os dados rolam no servidor (app/dice.py). Numa campanha, cada rolagem entra
   no registro da mesa, e este painel busca as rolagens dos outros a cada
   poucos segundos — o mestre vê o que os jogadores tiraram, e vice-versa.

   Configuração lida da página:
     #sheet-config  (ficha)   roll_url, feed_url, is_master
     #dice-config   (combate) free_url, feed_url, is_master
*/
(function (global) {
  "use strict";

  var config = {};
  ["sheet-config", "dice-config"].forEach(function (id) {
    var node = document.getElementById(id);
    if (!node) return;
    try { config = Object.assign(config, JSON.parse(node.textContent || "{}")); } catch (e) {}
  });

  var POLL_MS = 4000;
  var panel, entries, secretBox, lastId = 0, seen = {}, pollTimer = null, failures = 0;

  function ensurePanel() {
    if (panel) return;
    panel = document.createElement("aside");
    panel.className = "roll-log";
    panel.innerHTML =
      '<header><span>🎲 Rolagens' + (config.feed_url ? ' da mesa' : '') +
      '<span class="last" data-last></span></span>' +
      '<button class="btn btn-ghost btn-sm btn-icon" type="button" data-toggle title="Recolher">—</button></header>' +
      '<div class="entries"></div>' +
      '<div class="roll-manual">' +
      '<input type="text" placeholder="2d6+3" data-formula aria-label="Fórmula de dados">' +
      '<button class="btn btn-gold btn-sm" type="button" data-manual>Rolar</button></div>' +
      (config.is_master
        ? '<label class="roll-secret"><input type="checkbox" data-secret> rolagem secreta (só você vê)</label>'
        : '');
    document.body.appendChild(panel);
    document.body.classList.add("has-roll-log");
    entries = panel.querySelector(".entries");
    secretBox = panel.querySelector("[data-secret]");

    panel.querySelector("header").addEventListener("click", function () {
      panel.classList.toggle("collapsed");  // o cabeçalho inteiro abre e fecha — alvo maior no celular
    });
    var manualInput = panel.querySelector("[data-formula]");
    function manual() {
      var text = manualInput.value.trim();
      if (!text) return;
      formula(text, text);
    }
    panel.querySelector("[data-manual]").addEventListener("click", manual);
    manualInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter") { event.preventDefault(); manual(); }
    });
  }

  function render(roll, mine) {
    ensurePanel();
    if (roll.id) {
      if (seen[roll.id]) return;
      seen[roll.id] = true;
      // lastId NÃO anda aqui: se a minha rolagem (id 12) avançasse o marcador,
      // a de outra pessoa feita antes (id 11) nunca seria buscada. Só a
      // consulta ao servidor move o marcador.
    }
    var entry = document.createElement("div");
    entry.className = "roll-entry" + (roll.flag ? " " + roll.flag : "") + (mine ? " mine" : "");
    entry.innerHTML =
      '<div class="who"></div>' +
      '<div><strong></strong> <span class="res"></span></div>' +
      '<div class="det"></div>';
    entry.querySelector(".who").textContent =
      (roll.who || "") + (roll.secret ? " · 🔒 secreta" : "");
    entry.querySelector("strong").textContent = roll.label;
    entry.querySelector(".res").textContent = roll.result;
    var when = roll.at || "";
    if (roll.at_iso) {
      var parsed = new Date(roll.at_iso);
      if (!isNaN(parsed)) {
        when = parsed.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
      }
    }
    entry.querySelector(".det").textContent = roll.detail + (when ? " · " + when : "");
    entries.insertBefore(entry, entries.firstChild);
    // Recolhido (no celular fica como uma aba embaixo), o cabeçalho mostra o último resultado.
    var last = panel.querySelector("[data-last]");
    if (last) last.textContent = "· " + (roll.who ? roll.who + ": " : "") + roll.result;
    while (entries.children.length > 60) entries.removeChild(entries.lastChild);
  }

  function error(message) {
    render({ label: "Não rolou", result: "?", detail: message || "tente de novo", flag: "fail" }, true);
  }

  function send(url, body) {
    ensurePanel();
    panel.classList.remove("collapsed");
    if (!url) { error("rolagem indisponível nesta página"); return; }
    if (secretBox && secretBox.checked) body.secret = true;
    global.api(url, { body: body }).then(function (data) {
      if (data.ok) render(data.roll, true);
      else error(data.message);
    }).catch(function () { error("sem conexão com o servidor"); });
  }

  function roll(label, dice, bonus, target) {
    send(config.roll_url, {
      label: label,
      dice: Number(dice) || 0,
      bonus: Number(bonus) || 0,
      target: target === undefined ? null : Number(target)
    });
  }

  function formula(text, label) {
    send(config.roll_url || config.free_url, { formula: text, label: label || text });
  }

  /* ------------------------------------------------ histórico compartilhado */
  function poll() {
    if (!config.feed_url || document.hidden) return schedule();
    global.api(config.feed_url + "?desde=" + lastId).then(function (data) {
      failures = 0;
      (data.rolls || []).forEach(function (r) { render(r, false); });
      if (data.last) lastId = Math.max(lastId, data.last);
      schedule();
    }).catch(function () {
      failures += 1;
      schedule();
    });
  }

  function schedule() {
    clearTimeout(pollTimer);
    // Sem conexão, espaça as tentativas para não martelar o servidor.
    var wait = POLL_MS * Math.min(8, Math.pow(2, failures));
    pollTimer = setTimeout(poll, wait);
  }

  if (config.feed_url) {
    ensurePanel();
    panel.classList.add("collapsed");
    if (global.Live && global.Live.enabled) {
      // Vem junto com o resto das novidades da página (uma requisição só).
      global.Live.register("rolls", "", function (rolls) {
        (rolls || []).forEach(function (r) { render(r, false); });
      }, { fast: true });
    } else {
      poll();
      document.addEventListener("visibilitychange", function () {
        if (!document.hidden) poll();
      });
    }
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-roll]");
    if (!button) return;
    event.preventDefault();
    roll(button.dataset.label || "Rolagem", button.dataset.dice,
         button.dataset.bonus, button.dataset.target);
  });

  global.Dice = { roll: roll, formula: formula };
})(window);
