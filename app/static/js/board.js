/* Mapa tático: grade sobre a imagem do mapa, fichas dos combatentes e névoa.

   - Mover: arraste a ficha, ou toque nela e depois no quadrado de destino
     (no celular é o jeito mais preciso). Enquanto arrasta, mostra a distância.
   - O mestre move tudo, esconde fichas, pinta a névoa e configura a grade.
     Jogadores movem só as próprias fichas (se o mestre deixar).
   - Todo mundo acompanha ao vivo: a tela pergunta ao servidor a cada poucos
     segundos enquanto o mapa está aberto.
*/
(function () {
  "use strict";

  var POLL_MS = 3000;
  var DRAG_PX = 6;
  var ZOOM_KEY = "grimorio-board-cell";
  var ZOOM_MIN = 20, ZOOM_MAX = 96;

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function initials(name) {
    var parts = String(name || "?").trim().split(/\s+/);
    var first = parts[0] || "?";
    var last = parts.length > 1 ? parts[parts.length - 1] : "";
    // "Ghoul 3" vira "G3": o número diferencia as cópias no mapa.
    if (/^\d+$/.test(last)) return first.charAt(0).toUpperCase() + last;
    return (first.charAt(0) + (last ? last.charAt(0) : first.charAt(1) || "")).toUpperCase();
  }

  function readZoom() {
    var value = 0;
    try { value = Number(localStorage.getItem(ZOOM_KEY)); } catch (e) {}
    if (!value) value = window.matchMedia("(max-width: 640px)").matches ? 34 : 44;
    return Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, value));
  }

  function formatNumber(value) {
    return String(Math.round(value * 100) / 100).replace(".", ",");
  }

  document.querySelectorAll("[data-board]").forEach(function (panel) {
    var urls = {
      state: panel.dataset.stateUrl,
      move: panel.dataset.moveUrl,
      config: panel.dataset.configUrl,
      hide: panel.dataset.hideUrl,
      fog: panel.dataset.fogUrl
    };
    var scroller = panel.querySelector("[data-board-scroll]");
    var boardEl = panel.querySelector("[data-board-surface]");
    var image = panel.querySelector("[data-board-image]");
    var canvas = panel.querySelector("[data-board-fog]");
    var layer = panel.querySelector("[data-board-tokens]");
    var bench = panel.querySelector("[data-board-bench]");
    var info = panel.querySelector("[data-board-info]");
    var selectedBox = panel.querySelector("[data-board-selected]");
    var status = panel.querySelector("[data-board-status]");
    var config = panel.querySelector("[data-board-config]");

    var state = null;
    var cell = readZoom();
    var selected = null;      // uid da ficha selecionada
    var mode = "move";        // move | reveal | cover (névoa, só mestre)
    var drag = null;          // arraste de ficha em andamento
    var paint = null;         // pincel de névoa em andamento
    var busy = 0;             // pedidos em andamento: não sobrescreve a tela
    var configTimer = null;

    function setStatus(text, kind) {
      if (!status) return;
      status.textContent = text || "";
      status.dataset.kind = kind || "";
    }

    function findToken(uid) {
      if (!state) return null;
      var all = state.tokens.concat(state.bench);
      for (var i = 0; i < all.length; i++) if (all[i].uid === uid) return all[i];
      return null;
    }

    /* ------------------------------------------------------------ desenho */
    function drawFog() {
      var width = state.cols * cell, height = state.rows * cell;
      var ratio = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      canvas.style.width = width + "px";
      canvas.style.height = height + "px";
      var ctx = canvas.getContext("2d");
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, width, height);
      if (!state.fog) return;
      var open = {};
      state.revealed.forEach(function (key) { open[key] = true; });
      // Mestre enxerga através da névoa (para saber o que está escondido);
      // jogadores veem o quadrado fechado.
      ctx.fillStyle = state.is_master ? "rgba(6, 5, 12, .55)" : "rgb(10, 9, 16)";
      for (var y = 0; y < state.rows; y++) {
        for (var x = 0; x < state.cols; x++) {
          if (!open[x + "," + y]) ctx.fillRect(x * cell, y * cell, cell, cell);
        }
      }
    }

    function tokenNode(token) {
      var node = el("div", "token kind-" + token.kind +
        (token.turn ? " is-turn" : "") + (token.mine ? " is-mine" : "") +
        (token.hidden ? " is-hidden" : "") + (token.uid === selected ? " is-selected" : "") +
        (token.can_move ? " can-move" : ""));
      node.dataset.uid = token.uid;
      var face = el("div", "token-face");
      if (token.avatar) {
        face.style.backgroundImage = "url(\"" + token.avatar.replace(/"/g, "%22") + "\")";
        face.classList.add("has-avatar");
      } else {
        face.textContent = initials(token.name);
      }
      node.appendChild(face);

      var tip = token.name;
      if (token.hp !== undefined && token.hp_max) {
        var bar = el("div", "token-hp");
        var fill = el("span");
        var ratio = Math.max(0, Math.min(1, token.hp / token.hp_max));
        fill.style.width = Math.round(ratio * 100) + "%";
        fill.dataset.level = ratio > .5 ? "ok" : ratio > 0 ? "low" : "out";
        if (ratio <= 0) node.classList.add("is-down");
        bar.appendChild(fill);
        node.appendChild(bar);
        tip += " · " + token.hp + "/" + token.hp_max;
      } else if (token.health) {
        node.dataset.health = token.health;
        tip += " · " + token.health;
      }
      if (token.conditions && token.conditions.length) {
        node.appendChild(el("span", "token-cond", String(token.conditions.length)));
        tip += " · " + token.conditions.join(", ");
      }
      if (token.hidden) tip += " · escondida dos jogadores";
      node.title = tip;
      node.setAttribute("aria-label", tip);
      return node;
    }

    function renderTokens() {
      layer.innerHTML = "";
      var stacks = {};
      state.tokens.forEach(function (token) {
        var key = token.x + "," + token.y;
        var n = stacks[key] = (stacks[key] || 0) + 1;
        var node = tokenNode(token);
        var shift = (n - 1) * Math.max(4, cell * .18);  // empilhadas: leve deslocamento
        node.style.width = node.style.height = cell + "px";
        node.style.transform = "translate(" + (token.x * cell + shift) + "px," +
                                              (token.y * cell + shift) + "px)";
        layer.appendChild(node);
      });

      bench.innerHTML = "";
      bench.hidden = !state.bench.length;
      state.bench.forEach(function (token) {
        var chip = el("button", "bench-token" + (token.uid === selected ? " is-selected" : ""));
        chip.type = "button";
        chip.dataset.uid = token.uid;
        var face = tokenNode(token);
        face.style.width = face.style.height = "30px";
        chip.appendChild(face);
        chip.appendChild(el("span", "", token.name));
        chip.disabled = !token.can_move;
        bench.appendChild(chip);
      });
    }

    function renderSelected() {
      if (!selectedBox) return;
      var token = selected && findToken(selected);
      selectedBox.innerHTML = "";
      selectedBox.hidden = !token;
      if (!token) return;
      var onBoard = token.x !== undefined;
      selectedBox.appendChild(el("strong", "", token.name));
      selectedBox.appendChild(el("span", "muted small", onBoard
        ? "toque num quadrado para mover" : "toque num quadrado para colocar no mapa"));
      if (state.is_master && onBoard) {
        var hide = el("button", "btn btn-ghost btn-sm", token.hidden ? "👁 Mostrar" : "🙈 Esconder");
        hide.type = "button";
        hide.addEventListener("click", function () {
          send(urls.hide, { uid: token.uid, hidden: !token.hidden });
        });
        selectedBox.appendChild(hide);
      }
      if (onBoard && token.can_move) {
        var remove = el("button", "btn btn-ghost btn-sm", "Tirar do mapa");
        remove.type = "button";
        remove.addEventListener("click", function () {
          send(urls.move, { uid: token.uid, x: null, y: null });
          selected = null;
        });
        selectedBox.appendChild(remove);
      }
      var close = el("button", "btn btn-ghost btn-sm btn-icon", "✕");
      close.type = "button";
      close.title = "Desmarcar";
      close.addEventListener("click", function () { select(null); });
      selectedBox.appendChild(close);
    }

    function render() {
      if (!state) return;
      var width = state.cols * cell, height = state.rows * cell;
      boardEl.style.width = width + "px";
      boardEl.style.height = height + "px";
      boardEl.style.setProperty("--cell", cell + "px");
      boardEl.classList.toggle("show-grid", !!state.grid);
      boardEl.classList.toggle("painting", mode !== "move");
      if (state.map_url) {
        if (image.getAttribute("src") !== state.map_url) image.src = state.map_url;
        image.hidden = false;
      } else {
        image.hidden = true;
        image.removeAttribute("src");
      }
      drawFog();
      renderTokens();
      renderSelected();
      if (!drag) info.textContent = hint();
      syncConfig();
    }

    function hint() {
      var scale = state.cell_size ? "1 quadrado = " + formatNumber(state.cell_size) + " " + state.cell_unit : "";
      var turn = state.tokens.concat(state.bench).filter(function (t) { return t.turn; })[0];
      return [turn ? "Vez de " + turn.name : "", "Rodada " + (state.round_number || 1), scale]
        .filter(Boolean).join(" · ");
    }

    /* ------------------------------------------------------ configuração */
    function syncConfig() {
      if (!config || !state.is_master) return;
      var active = document.activeElement;
      function set(name, value) {
        var input = config.querySelector("[name=" + name + "]");
        if (!input || input === active) return;
        if (input.type === "checkbox") input.checked = !!value;
        else input.value = value === null || value === undefined ? "" : value;
      }
      var select = config.querySelector("[name=map_id]");
      if (select && select !== active) {
        var wanted = String(state.map_id || "");
        var options = [["", "Sem imagem (só a grade)"]].concat(state.maps.map(function (m) {
          return [String(m.id), m.title + (m.hidden ? " (escondido na galeria)" : "")];
        }));
        if (select.options.length !== options.length) {
          select.innerHTML = "";
          options.forEach(function (o) {
            var option = el("option", "", o[1]);
            option.value = o[0];
            select.appendChild(option);
          });
        }
        select.value = wanted;
      }
      set("cols", state.cols);
      set("rows", state.rows);
      set("cell_size", formatNumber(state.cell_size));
      set("cell_unit", state.cell_unit);
      set("grid", state.grid);
      set("fog", state.fog);
      set("players_move", state.players_move);
      panel.querySelectorAll("[data-fog-tools]").forEach(function (box) { box.hidden = !state.fog; });
      if (!state.fog && mode !== "move") setMode("move");
    }

    function readConfig() {
      var data = {};
      config.querySelectorAll("[name]").forEach(function (input) {
        if (input.type === "checkbox") data[input.name] = input.checked;
        else if (input.name === "cell_size") data[input.name] = input.value.replace(",", ".");
        else data[input.name] = input.value;
      });
      return data;
    }

    if (config) {
      var onConfig = function (event) {
        clearTimeout(configTimer);
        var delay = event.type === "change" ? 0 : 600;
        configTimer = setTimeout(function () { send(urls.config, readConfig()); }, delay);
      };
      config.addEventListener("input", onConfig);
      config.addEventListener("change", onConfig);
    }

    /* ---------------------------------------------------------- servidor */
    function adopt(data) {
      if (!data || !data.ok) return;
      state = data;
      state.tokens = state.tokens || [];
      state.bench = state.bench || [];
      state.revealed = state.revealed || [];
      if (selected && !findToken(selected)) selected = null;
      render();
    }

    function send(url, body) {
      busy += 1;
      setStatus("salvando…", "saving");
      return window.api(url, { body: body }).then(function (data) {
        busy -= 1;
        if (!data.ok) {
          setStatus(data.message || "não foi possível", "error");
          return refresh(true);
        }
        setStatus("");
        adopt(data);
      }).catch(function () {
        busy -= 1;
        setStatus("sem conexão", "error");
      });
    }

    function refresh(force) {
      if (!force && (busy || drag || paint || document.hidden || !panel.open)) return;
      return window.api(urls.state).then(function (data) {
        if (!force && (busy || drag || paint)) return;
        adopt(data);
      }).catch(function () {});
    }

    /* ------------------------------------------------------- interação */
    function cellAt(event) {
      var rect = boardEl.getBoundingClientRect();
      var x = Math.floor((event.clientX - rect.left) / cell);
      var y = Math.floor((event.clientY - rect.top) / cell);
      if (x < 0 || y < 0 || x >= state.cols || y >= state.rows) return null;
      return { x: x, y: y };
    }

    function distance(a, b) {
      // Diagonal conta como 1 quadrado (regra comum em D&D e derivados).
      var squares = Math.max(Math.abs(a.x - b.x), Math.abs(a.y - b.y));
      var text = squares + (squares === 1 ? " quadrado" : " quadrados");
      if (state.cell_size) text += " (" + formatNumber(squares * state.cell_size) + " " + state.cell_unit + ")";
      return text;
    }

    function capture(event) {
      // Mantém o arraste mesmo se o dedo sair do mapa. Alguns navegadores
      // recusam (ponteiro já solto): sem captura o arraste ainda funciona.
      try { boardEl.setPointerCapture(event.pointerId); } catch (e) {}
    }

    function select(uid) {
      selected = uid;
      render();
    }

    function placeSelected(target) {
      var token = findToken(selected);
      if (!token || !token.can_move) return false;
      if (token.x === target.x && token.y === target.y) return true;
      token.x = target.x;  // otimista: a resposta do servidor confirma
      token.y = target.y;
      state.bench = state.bench.filter(function (t) { return t.uid !== token.uid; });
      if (state.tokens.indexOf(token) < 0) state.tokens.push(token);
      render();
      send(urls.move, { uid: token.uid, x: target.x, y: target.y });
      return true;
    }

    function paintLine(target) {
      // Movimento rápido pula quadrados entre um evento e outro: pinta a reta
      // inteira desde o último quadrado pintado.
      var from = paint.last || target;
      var steps = Math.max(Math.abs(target.x - from.x), Math.abs(target.y - from.y));
      for (var i = 1; i <= steps; i++) {
        paintCell({ x: Math.round(from.x + (target.x - from.x) * i / steps),
                    y: Math.round(from.y + (target.y - from.y) * i / steps) });
      }
      paintCell(target);
      paint.last = target;
    }

    function paintCell(target) {
      var key = target.x + "," + target.y;
      if (paint.seen[key]) return;
      paint.seen[key] = true;
      paint.cells.push([target.x, target.y]);
      var index = state.revealed.indexOf(key);
      if (mode === "reveal" && index < 0) state.revealed.push(key);
      if (mode === "cover" && index >= 0) state.revealed.splice(index, 1);
      drawFog();
    }

    boardEl.addEventListener("pointerdown", function (event) {
      if (!state || event.button > 0) return;
      var target = cellAt(event);
      var tokenEl = event.target.closest(".token");

      if (state.is_master && mode !== "move") {
        if (!target) return;
        event.preventDefault();
        paint = { cells: [], seen: {}, pointer: event.pointerId };
        capture(event);
        paintLine(target);
        return;
      }

      if (tokenEl) {
        var token = findToken(tokenEl.dataset.uid);
        if (!token) return;
        drag = { uid: token.uid, node: tokenEl, from: { x: token.x, y: token.y },
                 startX: event.clientX, startY: event.clientY, moved: false,
                 pointer: event.pointerId, can: token.can_move };
        if (token.can_move) {
          event.preventDefault();
          capture(event);
        }
        return;
      }
      drag = { uid: null, startX: event.clientX, startY: event.clientY, moved: false,
               pointer: event.pointerId };
    });

    boardEl.addEventListener("pointermove", function (event) {
      if (paint && event.pointerId === paint.pointer) {
        var target = cellAt(event);
        if (target) paintLine(target);
        return;
      }
      if (!drag || event.pointerId !== drag.pointer) return;
      var dx = event.clientX - drag.startX, dy = event.clientY - drag.startY;
      if (!drag.moved && Math.abs(dx) + Math.abs(dy) < DRAG_PX) return;
      drag.moved = true;
      if (!drag.uid || !drag.can) return;
      drag.node.classList.add("is-dragging");
      var rect = boardEl.getBoundingClientRect();
      drag.node.style.transform = "translate(" + (event.clientX - rect.left - cell / 2) + "px," +
                                                 (event.clientY - rect.top - cell / 2) + "px)";
      var over = cellAt(event);
      if (over) info.textContent = "↔ " + distance(drag.from, over);
    });

    function endPointer(event, cancelled) {
      if (paint && event.pointerId === paint.pointer) {
        var cells = paint.cells, reveal = mode === "reveal";
        paint = null;
        if (!cancelled && cells.length) send(urls.fog, { cells: cells, reveal: reveal });
        return;
      }
      if (!drag || event.pointerId !== drag.pointer) return;
      var current = drag;
      drag = null;
      var target = cancelled ? null : cellAt(event);

      if (current.uid && current.moved && current.can) {
        selected = current.uid;
        if (!target || !placeSelected(target)) render();
        return;
      }
      if (current.moved || cancelled) { render(); return; }  // rolou a tela, não foi toque

      if (current.uid) {
        select(selected === current.uid ? null : current.uid);
      } else if (target && selected) {
        if (!placeSelected(target)) select(null);
      } else if (selected) {
        select(null);
      }
    }

    boardEl.addEventListener("pointerup", function (event) { endPointer(event, false); });
    boardEl.addEventListener("pointercancel", function (event) { endPointer(event, true); });

    bench.addEventListener("click", function (event) {
      var chip = event.target.closest(".bench-token");
      if (!chip || chip.disabled) return;
      select(selected === chip.dataset.uid ? null : chip.dataset.uid);
    });

    function setMode(next) {
      mode = next;
      panel.querySelectorAll("[data-board-mode]").forEach(function (button) {
        button.classList.toggle("active", button.dataset.boardMode === mode);
      });
      boardEl.classList.toggle("painting", mode !== "move");
    }

    panel.addEventListener("click", function (event) {
      var button = event.target.closest("[data-board-action], [data-board-mode]");
      if (!button || !panel.contains(button)) return;
      if (button.dataset.boardMode) { setMode(button.dataset.boardMode); return; }
      var action = button.dataset.boardAction;
      if (action === "zoom-in" || action === "zoom-out") {
        cell = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, cell + (action === "zoom-in" ? 6 : -6)));
        try { localStorage.setItem(ZOOM_KEY, String(cell)); } catch (e) {}
        render();
      } else if (action === "full") {
        var full = panel.classList.toggle("board-full");
        document.body.classList.toggle("board-lock", full);
        button.textContent = full ? "✕ Sair da tela cheia" : "⛶ Tela cheia";
      } else if (action === "reveal-all" || action === "cover-all") {
        if (action === "cover-all" && !confirm("Cobrir o mapa inteiro de névoa?")) return;
        send(urls.fog, { all: true, reveal: action === "reveal-all" });
      } else if (action === "fit-image") {
        if (!image.naturalWidth || !state) return;
        var rows = Math.round(state.cols * image.naturalHeight / image.naturalWidth);
        send(urls.config, { rows: Math.max(1, rows) });
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && panel.classList.contains("board-full")) {
        panel.querySelector("[data-board-action=full]").click();
      }
    });

    panel.addEventListener("toggle", function () {
      if (panel.open) refresh(true);
    });

    try {
      adopt(JSON.parse(panel.querySelector("[data-board-payload]").textContent));
    } catch (e) {
      refresh(true);
    }
    setInterval(refresh, POLL_MS);
    document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
  });
})();
