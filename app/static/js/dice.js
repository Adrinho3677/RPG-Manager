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
  var mode = "";            // "", "vantagem" ou "desvantagem" (vale para as rolagens da ficha)
  var seenWhispers = {};

  function renderWhisper(w) {
    ensurePanel();
    if (seenWhispers[w.id]) return;
    seenWhispers[w.id] = true;
    var mine = global.Live && w.from_id === global.Live.userId;
    var entry = document.createElement("div");
    entry.className = "roll-entry whisper" + (mine ? " mine" : "");
    entry.innerHTML = '<div class="who"></div><div class="det"></div>';
    entry.querySelector(".who").textContent = "🤫 " + (mine ? "você → " + w.to : w.from + " sussurrou");
    entry.querySelector(".det").textContent = w.text;
    entries.insertBefore(entry, entries.firstChild);
    if (!mine) {
      var last = panel.querySelector("[data-last]");
      if (last) last.textContent = "· 🤫 " + w.from;
      panel.classList.add("has-whisper");
    }
  }

  function ensurePanel() {
    if (panel) return;
    panel = document.createElement("aside");
    panel.className = "roll-log";
    panel.innerHTML =
      '<header><span>🎲 Rolagens' + (config.feed_url ? ' da mesa' : '') +
      '<span class="last" data-last></span></span>' +
      '<button class="btn btn-ghost btn-sm btn-icon" type="button" data-toggle title="Recolher">—</button></header>' +
      '<div class="entries"></div>' +
      '<div class="roll-modes" role="group" aria-label="Vantagem">' +
      '<button type="button" class="active" data-mode="">Normal</button>' +
      '<button type="button" data-mode="vantagem">Vantagem</button>' +
      '<button type="button" data-mode="desvantagem">Desvantagem</button></div>' +
      '<div class="roll-manual">' +
      '<input type="text" placeholder="2d6+3 · 2d20kh1 · 1d20+FOR" data-formula aria-label="Fórmula de dados">' +
      '<button class="btn btn-gold btn-sm" type="button" data-manual>Rolar</button></div>' +
      '<details class="roll-help"><summary>Fórmulas</summary>' +
      '<p><code>2d6+3</code> soma · <code>1d20+1d4+2</code> vários dados · <code>2d20kh1</code> fica com o maior ' +
      '(vantagem) · <code>2d20kl1</code> com o menor · <code>4d6kh3</code> · <code>3d6!</code> dado que explode · ' +
      '<code>d%</code> · na ficha, siglas: <code>1d20+FOR</code></p></details>' +
      (config.feed_url
        ? '<label class="roll-secret"><input type="checkbox" data-secret> ' +
          (config.is_master ? 'rolagem secreta (só você vê)' : 'só o mestre vê') + '</label>'
        : '') +
      (config.whisper_url
        ? '<div class="whisper-box">' +
          (config.is_master ? '<select data-whisper-to aria-label="Sussurrar para"></select>' : '') +
          '<input type="text" maxlength="500" data-whisper aria-label="Sussurro" placeholder="' +
          (config.is_master ? 'Sussurrar para um jogador…' : '🤫 Sussurrar ao mestre…') + '">' +
          '<button class="btn btn-ghost btn-sm" type="button" data-whisper-send>Enviar</button></div>'
        : '');
    document.body.appendChild(panel);
    document.body.classList.add("has-roll-log");
    entries = panel.querySelector(".entries");
    secretBox = panel.querySelector("[data-secret]");

    panel.querySelector("header").addEventListener("click", function () {
      panel.classList.remove("has-whisper");
      panel.classList.toggle("collapsed");  // o cabeçalho inteiro abre e fecha — alvo maior no celular
    });
    panel.querySelectorAll("[data-mode]").forEach(function (button) {
      button.addEventListener("click", function () {
        mode = button.dataset.mode;
        panel.querySelectorAll("[data-mode]").forEach(function (b) {
          b.classList.toggle("active", b === button);
        });
      });
    });
    var whisperInput = panel.querySelector("[data-whisper]");
    if (whisperInput) {
      var sendWhisper = function () {
        var text = whisperInput.value.trim();
        if (!text) return;
        var body = { text: text };
        var to = panel.querySelector("[data-whisper-to]");
        if (to) body.to = Number(to.value);
        global.api(config.whisper_url, { body: body }).then(function (data) {
          if (!data.ok) { error(data.message); return; }
          whisperInput.value = "";
          renderWhisper(data.whisper);
        }).catch(function () { error("sem conexão com o servidor"); });
      };
      panel.querySelector("[data-whisper-send]").addEventListener("click", sendWhisper);
      whisperInput.addEventListener("keydown", function (event) {
        if (event.key === "Enter") { event.preventDefault(); sendWhisper(); }
      });
    }
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
      label: label + (mode ? " (" + mode + ")" : ""),
      dice: Number(dice) || 0,
      bonus: Number(bonus) || 0,
      target: target === undefined ? null : Number(target),
      mode: mode
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
      if (config.whisper_url) {
        global.Live.register("whispers", "", function (data) {
          var select = panel.querySelector("[data-whisper-to]");
          if (select && data.people) {
            select.innerHTML = "";
            data.people.forEach(function (p) {
              var option = document.createElement("option");
              option.value = p.id;
              option.textContent = p.name;
              select.appendChild(option);
            });
            if (!data.people.length) {
              var none = document.createElement("option");
              none.textContent = "ninguém na mesa";
              none.value = "";
              select.appendChild(none);
            }
          }
          (data.items || []).forEach(renderWhisper);
        });
      }
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
