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

  // Grade quebrada (18,5 × 14,35): o último quadrado de cada borda fica parcial.
  function across(value) { return Math.max(1, Math.ceil(value - 1e-9)); }

  function formatNumber(value) {
    return String(Math.round(value * 100) / 100).replace(".", ",");
  }

  /* Áreas de efeito, em unidades de quadrado (origem pode cair no meio ou na
     quina de um quadrado). Uma ficha é atingida se o centro do quadrado dela
     está dentro da forma. Cone de 53° (largura igual ao comprimento, como em
     D&D); linha com 1 quadrado de largura. */
  var CONE_HALF = 26.57;
  function angleDiff(a, b) {
    var d = Math.abs(a - b) % 360;
    return d > 180 ? 360 - d : d;
  }
  function areaHits(area, token) {
    var half = (token.size || 1) / 2;
    var dx = token.x + half - area.ox, dy = token.y + half - area.oy;
    var dist = Math.sqrt(dx * dx + dy * dy);
    if (area.shape === "circle") return dist <= area.size + 1e-6;
    var rad = area.angle * Math.PI / 180;
    if (area.shape === "cone") {
      if (dist < 1e-6 || dist > area.size + 0.01) return false;
      return angleDiff(Math.atan2(dy, dx) * 180 / Math.PI, area.angle) <= CONE_HALF + 0.5;
    }
    var along = dx * Math.cos(rad) + dy * Math.sin(rad);
    var across = Math.abs(-dx * Math.sin(rad) + dy * Math.cos(rad));
    return along >= 0 && along <= area.size + 1e-6 && across <= 0.5 + 1e-6;
  }
  function areaShape(area) {
    var NS = "http://www.w3.org/2000/svg", node;
    if (area.shape === "circle") {
      node = document.createElementNS(NS, "circle");
      node.setAttribute("cx", area.ox);
      node.setAttribute("cy", area.oy);
      node.setAttribute("r", area.size);
      return node;
    }
    var rad = area.angle * Math.PI / 180, points = [];
    if (area.shape === "cone") {
      points.push([area.ox, area.oy]);
      for (var i = 0; i <= 12; i++) {
        var a = rad + (-CONE_HALF + i * CONE_HALF / 6) * Math.PI / 180;
        points.push([area.ox + Math.cos(a) * area.size, area.oy + Math.sin(a) * area.size]);
      }
    } else {
      var nx = -Math.sin(rad) * 0.5, ny = Math.cos(rad) * 0.5;
      var ex = area.ox + Math.cos(rad) * area.size, ey = area.oy + Math.sin(rad) * area.size;
      points = [[area.ox + nx, area.oy + ny], [ex + nx, ey + ny], [ex - nx, ey - ny], [area.ox - nx, area.oy - ny]];
    }
    node = document.createElementNS(NS, "polygon");
    node.setAttribute("points", points.map(function (p) { return p[0].toFixed(3) + "," + p[1].toFixed(3); }).join(" "));
    return node;
  }
  var SHAPE_ICON = { circle: "◯", cone: "◭", line: "━" };

  document.querySelectorAll("[data-board]").forEach(function (panel) {
    var urls = {
      state: panel.dataset.stateUrl,
      move: panel.dataset.moveUrl,
      config: panel.dataset.configUrl,
      hide: panel.dataset.hideUrl,
      fog: panel.dataset.fogUrl,
      area: panel.dataset.areaUrl,
      marker: panel.dataset.markerUrl,
      undo: panel.dataset.undoUrl
    };
    var reachCanvas = panel.querySelector("[data-board-reach]");
    var readonly = panel.dataset.readonly === "1";   // tela da TV: só mostra
    var view = panel.dataset.view || "";             // "mesa": visão dos jogadores
    var markerLayer = panel.querySelector("[data-board-markers]");
    var areaLayer = panel.querySelector("[data-board-areas]");
    var areaList = panel.querySelector("[data-board-area-list]");
    var sizeInput = panel.querySelector("[data-area-size]");
    var areaShapeNow = null;   // forma escolhida na barra (modo "area")
    var aiming = null;         // área sendo mirada agora
    var drawing = null;        // forma de névoa sendo desenhada agora
    var selectedShape = null;  // id da forma de névoa selecionada (mestre)
    var preview = false;       // "prévia do jogador": ver a névoa fechada
    var selectedMarker = null; // id do marcador selecionado (mestre)
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
    // move | area | marker | fog-rect | fog-poly | fog-circle | fog-brush | fog-pick
    var mode = "move";
    var drag = null;          // arraste de ficha em andamento
    var paint = null;         // arraste de forma de névoa em andamento
    var busy = 0;             // pedidos em andamento: não sobrescreve a tela
    var configTimer = null;
    var configDirty = false;   // há mudança digitada ainda não enviada
    var afterSend = function () {};

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
    /* Até onde a ficha selecionada anda: quadrados a no máximo "deslocamento"
       de distância (diagonal conta 1, como na régua). */
    function drawReach() {
      var width = state.cols * cell, height = state.rows * cell;
      var ratio = window.devicePixelRatio || 1;
      reachCanvas.width = Math.round(width * ratio);
      reachCanvas.height = Math.round(height * ratio);
      reachCanvas.style.width = width + "px";
      reachCanvas.style.height = height + "px";
      var ctx = reachCanvas.getContext("2d");
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, width, height);
      var token = selected && findToken(selected);
      if (!token || token.x === undefined || !token.speed || !token.can_move || drag) return;
      var reach = Math.floor(token.speed + 1e-6), size = token.size || 1;
      ctx.fillStyle = "rgba(63, 178, 127, .22)";
      ctx.strokeStyle = "rgba(63, 178, 127, .55)";
      for (var y = 0; y < across(state.rows); y++) {
        for (var x = 0; x < across(state.cols); x++) {
          var dx = x < token.x ? token.x - x : Math.max(0, x - (token.x + size - 1));
          var dy = y < token.y ? token.y - y : Math.max(0, y - (token.y + size - 1));
          if (Math.max(dx, dy) <= reach && (dx || dy)) {
            ctx.fillRect(x * cell + 1, y * cell + 1, cell - 2, cell - 2);
          }
        }
      }
    }

    /* Névoa por formas, no estilo do Owlbear Rodeo: cada forma põe névoa, e a
       forma "cortada" abre um buraco em toda a névoa. A máscara (branco =
       coberto) sai daí; o servidor desenha igualzinho na imagem que o jogador
       recebe (app/fogimage.py). */
    function tracePath(ctx, shape) {
      var points = shape.points;
      if (shape.kind === "rect") {
        var a = points[0], b = points[points.length - 1];
        ctx.rect(Math.min(a[0], b[0]) * cell, Math.min(a[1], b[1]) * cell,
                 Math.abs(b[0] - a[0]) * cell, Math.abs(b[1] - a[1]) * cell);
        return;
      }
      if (shape.kind === "circle") {
        ctx.arc(points[0][0] * cell, points[0][1] * cell, Math.max(1, shape.size * cell), 0, Math.PI * 2);
        return;
      }
      points.forEach(function (point, index) {
        var px = point[0] * cell, py = point[1] * cell;
        if (index) ctx.lineTo(px, py);
        else ctx.moveTo(px, py);
      });
      if (shape.kind === "poly") ctx.closePath();
    }

    function paintShape(ctx, shape) {
      ctx.beginPath();
      if (shape.kind === "brush") {
        if (shape.points.length === 1) {
          var only = shape.points[0];
          ctx.arc(only[0] * cell, only[1] * cell, Math.max(1, shape.size * cell), 0, Math.PI * 2);
          ctx.fill();
          return;
        }
        ctx.lineCap = ctx.lineJoin = "round";
        ctx.lineWidth = Math.max(1, shape.size * 2 * cell);
        tracePath(ctx, shape);
        ctx.stroke();
        return;
      }
      tracePath(ctx, shape);
      ctx.fill();
    }

    function fogShapes() {
      var shapes = ((state.fog_layer || {}).shapes || []).slice();
      if (drawing) {
        // Polígono em andamento: a próxima quina acompanha o mouse.
        shapes.push(drawing.live && drawing.kind === "poly"
          ? { kind: "poly", cut: drawing.cut, size: drawing.size,
              points: drawing.points.concat([drawing.live]) }
          : drawing);
      }
      return shapes;
    }

    function fogMask(width, height) {
      var mask = document.createElement("canvas");
      mask.width = Math.max(1, Math.round(width));
      mask.height = Math.max(1, Math.round(height));
      var ctx = mask.getContext("2d");
      ctx.fillStyle = ctx.strokeStyle = "#fff";
      if ((state.fog_layer || {}).fill) ctx.fillRect(0, 0, width, height);
      var shapes = fogShapes();
      shapes.forEach(function (shape) { if (!shape.cut) paintShape(ctx, shape); });
      ctx.globalCompositeOperation = "destination-out";
      shapes.forEach(function (shape) { if (shape.cut) paintShape(ctx, shape); });
      ctx.globalCompositeOperation = "source-over";
      return mask;
    }

    /* Contorno das formas, só para o mestre: é por ele que se escolhe a sala
       para revelar. Tracejado = forma cortada (já revelada). */
    function outlineShapes(ctx) {
      ctx.save();
      fogShapes().forEach(function (shape) {
        var on = shape.id && shape.id === selectedShape;
        ctx.strokeStyle = on ? "rgba(233, 196, 106, .95)"
          : shape.cut ? "rgba(110, 220, 180, .55)" : "rgba(170, 160, 255, .45)";
        ctx.lineWidth = on ? 3 : 1.5;
        ctx.setLineDash(shape.cut ? [7, 5] : []);
        ctx.beginPath();
        tracePath(ctx, shape);
        ctx.stroke();
      });
      ctx.restore();
    }

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
      var asMaster = state.is_master && !preview;
      ctx.drawImage(fogMask(width, height), 0, 0, width, height);
      // Mestre enxerga através da névoa (para saber o que está escondido);
      // o jogador — e a prévia — veem fechado.
      ctx.globalCompositeOperation = "source-in";
      ctx.fillStyle = asMaster ? "rgba(6, 5, 12, .62)" : "rgb(10, 9, 16)";
      ctx.fillRect(0, 0, width, height);
      ctx.globalCompositeOperation = "source-over";
      if (asMaster) outlineShapes(ctx);
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
        var size = token.size || 1;
        var shift = size === 1 ? (n - 1) * Math.max(4, cell * .18) : 0;  // empilhadas: leve deslocamento
        node.style.width = node.style.height = size * cell + "px";
        if (size > 1) node.classList.add("is-large");
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

    function renderMarkers() {
      markerLayer.innerHTML = "";
      (state.markers || []).forEach(function (marker) {
        var node = el("div", "marker" + (marker.hidden ? " is-hidden" : "") +
                              (marker.id === selectedMarker ? " is-selected" : ""), marker.icon);
        node.dataset.marker = marker.id;
        node.style.width = node.style.height = cell + "px";
        node.style.transform = "translate(" + marker.x * cell + "px," + marker.y * cell + "px)";
        node.title = (marker.label || marker.type) + (marker.hidden ? " · escondido dos jogadores" : "");
        markerLayer.appendChild(node);
      });
    }

    function areaCells(area) {
      return state.tokens.filter(function (t) { return areaHits(area, t); });
    }

    function sizeInCells() {
      var value = parseFloat(String(sizeInput ? sizeInput.value : "1").replace(",", "."));
      if (!(value > 0)) return 0;
      return state.cell_size ? value / state.cell_size : value;
    }

    function renderAreas() {
      var width = state.cols * cell, height = state.rows * cell;
      areaLayer.setAttribute("viewBox", "0 0 " + state.cols + " " + state.rows);
      areaLayer.setAttribute("width", width);
      areaLayer.setAttribute("height", height);
      areaLayer.innerHTML = "";
      var all = (state.areas || []).slice();
      if (aiming) all.push(aiming);
      all.forEach(function (area) {
        var node = areaShape(area);
        node.setAttribute("class", "area" + (area === aiming ? " is-aiming" : "") +
                                   (area.owner === state.user_id ? " is-mine" : ""));
        areaLayer.appendChild(node);
      });

      if (!areaList) return;
      areaList.innerHTML = "";
      areaList.hidden = !(state.areas || []).length;
      (state.areas || []).forEach(function (area) {
        var row = el("div", "area-row");
        var sizeText = state.cell_size ? formatNumber(area.size * state.cell_size) + " " + state.cell_unit
          : formatNumber(area.size) + " quadrados";
        var hit = areaCells(area).map(function (t) { return t.name; });
        row.appendChild(el("span", "", SHAPE_ICON[area.shape] + " " + sizeText + " · " + (area.who || "?")));
        row.appendChild(el("span", "muted small", hit.length ? "atinge: " + hit.join(", ") : "não atinge ninguém"));
        if (state.is_master || area.owner === state.user_id) {
          var remove = el("button", "btn btn-ghost btn-sm btn-icon", "✕");
          remove.type = "button";
          remove.title = "Tirar a área";
          remove.addEventListener("click", function () { send(urls.area, { op: "remove", id: area.id }); });
          row.appendChild(remove);
        }
        areaList.appendChild(row);
      });
      if (state.is_master && (state.areas || []).length > 1) {
        var clear = el("button", "btn btn-ghost btn-sm", "Limpar todas as áreas");
        clear.type = "button";
        clear.addEventListener("click", function () { send(urls.area, { op: "clear" }); });
        areaList.appendChild(clear);
      }
    }

    function renderMarkerSelected() {
      var marker = (state.markers || []).filter(function (m) { return m.id === selectedMarker; })[0];
      if (!marker) { selectedMarker = null; return false; }
      selectedBox.hidden = false;
      selectedBox.appendChild(el("strong", "", marker.icon + " " + (marker.label || marker.type)));
      selectedBox.appendChild(el("span", "muted small", "toque num quadrado para mover"));
      var label = el("input");
      label.type = "text";
      label.placeholder = "Rótulo (ex.: porta trancada)";
      label.value = marker.label || "";
      label.maxLength = 60;
      label.className = "marker-label";
      label.setAttribute("aria-label", "Rótulo do marcador");
      label.addEventListener("change", function () {
        send(urls.marker, { op: "update", id: marker.id, label: label.value });
      });
      selectedBox.appendChild(label);
      var toggle = el("button", "btn btn-ghost btn-sm", marker.hidden ? "👁 Revelar" : "🙈 Esconder");
      toggle.type = "button";
      toggle.addEventListener("click", function () {
        send(urls.marker, { op: "update", id: marker.id, hidden: !marker.hidden });
      });
      selectedBox.appendChild(toggle);
      var remove = el("button", "btn btn-ghost btn-sm", "Remover");
      remove.type = "button";
      remove.addEventListener("click", function () {
        selectedMarker = null;
        send(urls.marker, { op: "remove", id: marker.id });
      });
      selectedBox.appendChild(remove);
      var close = el("button", "btn btn-ghost btn-sm btn-icon", "✕");
      close.type = "button";
      close.title = "Desmarcar";
      close.addEventListener("click", function () { selectedMarker = null; render(); });
      selectedBox.appendChild(close);
      return true;
    }

    function renderSelected() {
      if (!selectedBox) return;
      if (selectedMarker) {
        selectedBox.innerHTML = "";
        if (renderMarkerSelected()) return;
      }
      var token = selected && findToken(selected);
      selectedBox.innerHTML = "";
      selectedBox.hidden = !token;
      if (!token) return;
      var onBoard = token.x !== undefined;
      selectedBox.appendChild(el("strong", "", token.name));
      selectedBox.appendChild(el("span", "muted small", onBoard
        ? "toque num quadrado para mover" : "toque num quadrado para colocar no mapa"));
      if (onBoard && token.speed) {
        selectedBox.appendChild(el("span", "tag tag-ok", "anda " + formatNumber(token.speed) +
          (token.speed === 1 ? " quadrado" : " quadrados") +
          (state.cell_size ? " (" + formatNumber(token.speed * state.cell_size) + " " + state.cell_unit + ")" : "")));
      }
      if (state.is_master && onBoard) {
        var sizeSelect = el("select", "token-size");
        sizeSelect.setAttribute("aria-label", "Tamanho da criatura");
        [1, 2, 3, 4].forEach(function (n) {
          var option = el("option", "", n + "×" + n + (n === 1 ? " (normal)" : n === 2 ? " (grande)" : n === 3 ? " (enorme)" : " (imensa)"));
          option.value = n;
          if ((token.size || 1) === n) option.selected = true;
          sizeSelect.appendChild(option);
        });
        sizeSelect.addEventListener("change", function () {
          send(urls.hide, { uid: token.uid, size: Number(sizeSelect.value) });
        });
        selectedBox.appendChild(sizeSelect);
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

    function fitCell() {
      // TV: o mapa inteiro cabe na tela, sem rolagem.
      var box = scroller.getBoundingClientRect();
      var available = Math.max(200, window.innerHeight - box.top - 12);
      var size = Math.floor(Math.min(scroller.clientWidth / state.cols, available / state.rows));
      return Math.max(ZOOM_MIN, Math.min(160, size));
    }

    function render() {
      if (!state) return;
      if (panel.dataset.fit) cell = fitCell();
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
      drawReach();
      drawFog();
      renderMarkers();
      renderAreas();
      renderTokens();
      renderSelected();
      syncFogTools();
      if (!drag && !aiming && !drawing) {
        if (mode === "move") info.textContent = hint();
        else if (mode.indexOf("fog-") === 0) fogInfo();
      }
      var unit = panel.querySelector("[data-area-unit]");
      if (unit) unit.textContent = state.cell_size ? state.cell_unit : "quadrados";
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
      // Enquanto houver coisa digitada ainda não enviada, a resposta do
      // servidor não pode reescrever os campos: o mestre veria o que digitou
      // voltar ao valor antigo no meio da digitação.
      if (!config || !state.is_master || configDirty) return;
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
      set("cols", formatNumber(state.cols));
      set("rows", formatNumber(state.rows));
      set("cell_size", formatNumber(state.cell_size));
      set("cell_unit", state.cell_unit);
      set("grid", state.grid);
      set("fog", state.fog);
      set("players_move", state.players_move);
      panel.querySelectorAll("[data-fog-tools]").forEach(function (box) { box.hidden = !state.fog; });
      var warning = config.querySelector("[data-fog-warning]");
      var current = state.maps.filter(function (m) { return m.id === state.map_id; })[0];
      if (warning) warning.hidden = !(state.fog && current && !current.hidden);
      if (!state.fog && mode.indexOf("fog-") === 0) setMode("move");
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
        configDirty = true;
        clearTimeout(configTimer);
        var delay = event.type === "change" ? 0 : 600;
        configTimer = setTimeout(function () {
          configDirty = false;   // o que vai agora é exatamente o que está na tela
          send(urls.config, readConfig());
        }, delay);
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
      state.fog_layer = state.fog_layer || { fill: false, shapes: [] };
      if (selectedShape && !findShape(selectedShape)) selectedShape = null;
      state.markers = state.markers || [];
      state.areas = state.areas || [];
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
        afterSend();
      }).catch(function () {
        busy -= 1;
        setStatus("sem conexão", "error");
      });
    }

    function refresh(force) {
      if (!force && (busy || drag || paint || aiming || document.hidden || !panel.open)) return;
      return window.api(urls.state).then(function (data) {
        if (!force && (busy || drag || paint || aiming)) return;
        adopt(data);
      }).catch(function () {});
    }

    /* ------------------------------------------------------- interação */
    function cellAt(event) {
      var rect = boardEl.getBoundingClientRect();
      var x = Math.floor((event.clientX - rect.left) / cell);
      var y = Math.floor((event.clientY - rect.top) / cell);
      if (x < 0 || y < 0 || x >= across(state.cols) || y >= across(state.rows)) return null;
      return { x: x, y: y };
    }

    function pointAt(event, snap) {
      var rect = boardEl.getBoundingClientRect();
      var x = (event.clientX - rect.left) / cell, y = (event.clientY - rect.top) / cell;
      if (snap) { x = Math.round(x * 2) / 2; y = Math.round(y * 2) / 2; }  // centro ou quina
      return { x: Math.max(0, Math.min(state.cols, x)), y: Math.max(0, Math.min(state.rows, y)) };  // em quadrados
    }

    function aimInfo() {
      var hit = areaCells(aiming).map(function (t) { return t.name; });
      info.textContent = SHAPE_ICON[aiming.shape] + " " + (hit.length ? "atinge: " + hit.join(", ") : "não atinge ninguém");
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
      var size = token.size || 1;
      target = { x: Math.max(0, Math.min(across(state.cols) - size, target.x)),
                 y: Math.max(0, Math.min(across(state.rows) - size, target.y)) };
      if (token.x === target.x && token.y === target.y) return true;
      token.x = target.x;  // otimista: a resposta do servidor confirma
      token.y = target.y;
      state.bench = state.bench.filter(function (t) { return t.uid !== token.uid; });
      if (state.tokens.indexOf(token) < 0) state.tokens.push(token);
      render();
      send(urls.move, { uid: token.uid, x: target.x, y: target.y });
      return true;
    }

    function brushSize() {
      var input = panel.querySelector("[data-brush-size]");
      var value = input ? parseFloat(String(input.value).replace(",", ".")) : 1.5;
      return Math.max(0.1, Math.min(state.brush || 12, value || 1.5));
    }

    function cutNow() {
      var box = panel.querySelector("[data-fog-cut]");
      return !!(box && box.checked);
    }

    function findShape(id) {
      return ((state.fog_layer || {}).shapes || []).filter(function (s) { return s.id === id; })[0];
    }

    /* Ponto do mapa, em quadrados. As formas grudam na grade (como no Owlbear);
       segurando Ctrl a quina cai onde o mouse está. O pincel é sempre livre. */
    function fogPoint(event, free) {
      var rect = boardEl.getBoundingClientRect();
      var x = (event.clientX - rect.left) / cell, y = (event.clientY - rect.top) / cell;
      if (!free && !event.ctrlKey && !event.metaKey) { x = Math.round(x); y = Math.round(y); }
      return [Math.round(Math.max(0, Math.min(state.cols, x)) * 1000) / 1000,
              Math.round(Math.max(0, Math.min(state.rows, y)) * 1000) / 1000];
    }

    /* Mesma conta do servidor (app/board.py): o ponto está dentro da forma? */
    function inShape(shape, x, y) {
      var points = shape.points;
      if (shape.kind === "rect") {
        var a = points[0], b = points[1];
        return x >= Math.min(a[0], b[0]) && x <= Math.max(a[0], b[0]) &&
               y >= Math.min(a[1], b[1]) && y <= Math.max(a[1], b[1]);
      }
      if (shape.kind === "circle") {
        var dx = x - points[0][0], dy = y - points[0][1];
        return dx * dx + dy * dy <= shape.size * shape.size;
      }
      if (shape.kind === "poly") {
        var inside = false;
        for (var i = 0; i < points.length; i++) {
          var px = points[i][0], py = points[i][1];
          var q = points[(i + 1) % points.length], qx = q[0], qy = q[1];
          if ((py > y) !== (qy > y) && x < px + (y - py) * (qx - px) / ((qy - py) || 1e-9)) inside = !inside;
        }
        return inside;
      }
      var radius = shape.size;
      for (var j = 0; j < points.length; j++) {
        var ax = x - points[j][0], ay = y - points[j][1];
        if (ax * ax + ay * ay <= radius * radius) return true;
        if (j + 1 < points.length) {
          var vx = points[j + 1][0] - points[j][0], vy = points[j + 1][1] - points[j][1];
          var len = vx * vx + vy * vy;
          if (!len) continue;
          var t = Math.max(0, Math.min(1, (ax * vx + ay * vy) / len));
          var ox = ax - t * vx, oy = ay - t * vy;
          if (ox * ox + oy * oy <= radius * radius) return true;
        }
      }
      return false;
    }

    function shapeAt(point) {
      var shapes = (state.fog_layer || {}).shapes || [];
      for (var i = shapes.length - 1; i >= 0; i--) {     // a de cima primeiro
        if (inShape(shapes[i], point[0], point[1])) return shapes[i];
      }
      return null;
    }

    var FOG_HINT = {
      "fog-rect": "Arraste para cobrir um retângulo de névoa",
      "fog-circle": "Arraste do centro para fora: névoa redonda",
      "fog-poly": "Clique em cada quina; Enter (ou duplo clique) fecha a forma, Esc cancela",
      "fog-brush": "Arraste para pintar névoa à mão livre",
      "fog-pick": "Clique numa forma de névoa para revelar, cobrir ou apagar"
    };

    function fogInfo() {
      if (mode === "fog-pick") {
        var shape = selectedShape && findShape(selectedShape);
        info.textContent = shape
          ? "Forma selecionada: " + (shape.cut ? "revelada (cortada)" : "cobrindo o mapa")
          : FOG_HINT["fog-pick"];
        return;
      }
      info.textContent = (FOG_HINT[mode] || "") +
        (cutNow() && mode !== "fog-pick" ? " — já cortada (revela)" : "");
    }

    /* Os botões de revelar/cobrir/apagar só fazem sentido com uma forma escolhida. */
    function syncFogTools() {
      panel.querySelectorAll("[data-fog-shape-tools]").forEach(function (box) {
        box.hidden = !(state && state.fog && selectedShape);
      });
    }

    function selectShape(id) {
      selectedShape = id;
      syncFogTools();
      fogInfo();
      drawFog();
    }

    function sendShape(shape) {
      send(urls.fog, { op: "add", kind: shape.kind, points: shape.points,
                       size: shape.size, cut: shape.cut });
    }

    function validShape(shape) {
      if (shape.kind === "rect") {
        var a = shape.points[0], b = shape.points[1];
        return Math.abs(b[0] - a[0]) > 0.1 && Math.abs(b[1] - a[1]) > 0.1;
      }
      if (shape.kind === "circle") return shape.size > 0.1;
      if (shape.kind === "poly") return shape.points.length >= 3;
      return shape.points.length > 0;
    }

    function finishPoly(cancelled) {
      var shape = drawing;
      drawing = null;
      if (!cancelled && shape && validShape(shape)) sendShape(shape);
      else drawFog();
    }

    boardEl.addEventListener("pointerdown", function (event) {
      if (!state || event.button > 0 || readonly) return;
      var target = cellAt(event);
      var tokenEl = event.target.closest(".token");

      if (mode === "area") {
        var size = sizeInCells();
        if (!size) { setStatus("informe o tamanho da área", "error"); return; }
        event.preventDefault();
        var origin = pointAt(event, true);
        aiming = { shape: areaShapeNow, ox: origin.x, oy: origin.y, angle: 0, size: size,
                   owner: state.user_id, pointer: event.pointerId };
        capture(event);
        renderAreas();
        aimInfo();
        return;
      }

      if (state.is_master && mode === "marker") {
        if (!target) return;
        var type = panel.querySelector("[data-marker-type]");
        send(urls.marker, { op: "add", type: type ? type.value : "nota", x: target.x, y: target.y });
        setMode("move");
        return;
      }

      if (state.is_master && mode.indexOf("fog-") === 0) {
        event.preventDefault();
        var kind = mode.slice(4);
        if (kind === "pick") {
          var hit = shapeAt(fogPoint(event, true));
          selectShape(hit && hit.id !== selectedShape ? hit.id : null);
          return;
        }
        if (kind === "poly") {
          if (!drawing) drawing = { kind: "poly", size: 1, cut: cutNow(), points: [], live: null };
          drawing.points.push(fogPoint(event));
          drawFog();
          return;
        }
        var start = fogPoint(event, kind === "brush");
        paint = { pointer: event.pointerId, kind: kind };
        drawing = kind === "brush"
          ? { kind: "brush", size: brushSize(), cut: cutNow(), points: [start] }
          : { kind: kind, size: 0.1, cut: cutNow(), points: kind === "rect" ? [start, start] : [start] };
        capture(event);
        drawFog();
        return;
      }

      var markerEl = event.target.closest(".marker");
      if (markerEl) {
        if (state.is_master) {
          selectedMarker = selectedMarker === markerEl.dataset.marker ? null : markerEl.dataset.marker;
          selected = null;
          render();
        } else {
          info.textContent = markerEl.title;
        }
        return;
      }

      if (tokenEl) {
        var token = findToken(tokenEl.dataset.uid);
        if (!token) return;
        var grabbed = cellAt(event) || { x: token.x, y: token.y };
        drag = { uid: token.uid, node: tokenEl, from: { x: token.x, y: token.y },
                 startX: event.clientX, startY: event.clientY, moved: false,
                 pointer: event.pointerId, can: token.can_move,
                 grab: { x: Math.max(0, grabbed.x - (token.x || 0)), y: Math.max(0, grabbed.y - (token.y || 0)) } };
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
      if (aiming && event.pointerId === aiming.pointer) {
        if (aiming.shape !== "circle") {
          var p = pointAt(event, false);
          if (Math.abs(p.x - aiming.ox) + Math.abs(p.y - aiming.oy) > 0.2) {
            aiming.angle = (Math.atan2(p.y - aiming.oy, p.x - aiming.ox) * 180 / Math.PI + 360) % 360;
          }
        } else {
          var c = pointAt(event, true);
          aiming.ox = c.x;
          aiming.oy = c.y;
        }
        renderAreas();
        aimInfo();
        return;
      }
      if (paint && event.pointerId === paint.pointer) {
        var point = fogPoint(event, paint.kind === "brush");
        if (paint.kind === "rect") {
          drawing.points[1] = point;
        } else if (paint.kind === "circle") {
          var ex = point[0] - drawing.points[0][0], ey = point[1] - drawing.points[0][1];
          drawing.size = Math.max(0.1, Math.min(state.brush || 12, Math.sqrt(ex * ex + ey * ey)));
        } else {
          // Só guarda pontos que andaram: um traço parado não vira 400 pontos.
          var last = drawing.points[drawing.points.length - 1];
          if (Math.abs(last[0] - point[0]) + Math.abs(last[1] - point[1]) < 0.08) return;
          drawing.points.push(point);
        }
        drawFog();
        return;
      }
      if (drawing && drawing.kind === "poly") {        // próxima quina no mouse
        drawing.live = fogPoint(event);
        drawFog();
        return;
      }
      if (!drag || event.pointerId !== drag.pointer) return;
      var dx = event.clientX - drag.startX, dy = event.clientY - drag.startY;
      if (!drag.moved && Math.abs(dx) + Math.abs(dy) < DRAG_PX) return;
      drag.moved = true;
      if (!drag.uid || !drag.can) return;
      drag.node.classList.add("is-dragging");
      var rect = boardEl.getBoundingClientRect();
      drag.node.style.transform = "translate(" + (event.clientX - rect.left - (drag.grab.x + .5) * cell) + "px," +
                                                 (event.clientY - rect.top - (drag.grab.y + .5) * cell) + "px)";
      var over = cellAt(event);
      if (over) info.textContent = "↔ " + distance(drag.from, { x: over.x - drag.grab.x, y: over.y - drag.grab.y });
    });

    function endPointer(event, cancelled) {
      if (aiming && event.pointerId === aiming.pointer) {
        var area = aiming;
        aiming = null;
        setMode("move");
        if (!cancelled) {
          send(urls.area, { op: "add", shape: area.shape, ox: area.ox, oy: area.oy,
                            angle: area.angle, size: area.size });
        } else {
          render();
        }
        return;
      }
      if (paint && event.pointerId === paint.pointer) {
        var shape = drawing;
        paint = null;
        drawing = null;
        if (!cancelled && shape && validShape(shape)) sendShape(shape);
        else drawFog();
        return;
      }
      if (!drag || event.pointerId !== drag.pointer) return;
      var current = drag;
      drag = null;
      var target = cancelled ? null : cellAt(event);

      if (current.uid && current.moved && current.can) {
        selected = current.uid;
        if (target) target = { x: target.x - current.grab.x, y: target.y - current.grab.y };
        if (!target || !placeSelected(target)) render();
        return;
      }
      if (current.moved || cancelled) { render(); return; }  // rolou a tela, não foi toque

      if (!current.uid && target && selectedMarker && state.is_master) {
        send(urls.marker, { op: "update", id: selectedMarker, x: target.x, y: target.y });
        return;
      }
      if (current.uid) {
        selectedMarker = null;
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

    function setMode(next, shape) {
      if (drawing && drawing.kind === "poly") finishPoly(true);
      mode = next;
      if (next !== "fog-pick" && selectedShape) selectShape(null);
      areaShapeNow = next === "area" ? shape : null;
      panel.querySelectorAll("[data-board-mode]").forEach(function (button) {
        button.classList.toggle("active", button.dataset.boardMode === mode);
      });
      panel.querySelectorAll("[data-area-shape]").forEach(function (button) {
        button.classList.toggle("active", button.dataset.areaShape === areaShapeNow);
      });
      boardEl.classList.toggle("painting", mode !== "move");
      if (mode === "area") info.textContent = "Clique no mapa" +
        (shape === "circle" ? " no centro da área" : " na origem e arraste para mirar");
      else if (mode === "marker") info.textContent = "Clique no quadrado do marcador";
      else if (mode.indexOf("fog-") === 0) fogInfo();
      else if (state) info.textContent = hint();
    }

    panel.addEventListener("change", function (event) {
      if (event.target.matches("[data-fog-cut]") && mode.indexOf("fog-") === 0) fogInfo();
    });

    panel.addEventListener("click", function (event) {
      var button = event.target.closest("[data-board-action], [data-board-mode], [data-area-shape]");
      if (!button || !panel.contains(button)) return;
      if (button.dataset.areaShape) {
        if (mode === "area" && areaShapeNow === button.dataset.areaShape) setMode("move");
        else setMode("area", button.dataset.areaShape);
        return;
      }
      if (button.dataset.boardMode) {
        setMode(mode === button.dataset.boardMode && mode !== "move" ? "move" : button.dataset.boardMode);
        return;
      }
      var action = button.dataset.boardAction;
      if (action === "zoom-in" || action === "zoom-out") {
        cell = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, cell + (action === "zoom-in" ? 6 : -6)));
        try { localStorage.setItem(ZOOM_KEY, String(cell)); } catch (e) {}
        render();
      } else if (action === "full") {
        var full = panel.classList.toggle("board-full");
        document.body.classList.toggle("board-lock", full);
        button.textContent = full ? "✕ Sair da tela cheia" : "⛶ Tela cheia";
      } else if (action === "fog-fill") {
        send(urls.fog, { op: "fill", value: !(state.fog_layer || {}).fill });
      } else if (action === "fog-clear") {
        if (!confirm("Apagar toda a névoa deste mapa?")) return;
        selectedShape = null;
        send(urls.fog, { op: "clear" });
      } else if (action === "fog-cut" || action === "fog-uncut" || action === "fog-remove") {
        if (!selectedShape) return;
        var shapeId = selectedShape;
        if (action === "fog-remove") selectedShape = null;
        send(urls.fog, { op: action.slice(4), id: shapeId });
      } else if (action === "fog-preview") {
        preview = !preview;
        button.classList.toggle("active", preview);
        drawFog();
      } else if (action === "undo") {
        send(urls.undo, {});
      } else if (action === "fit-image") {
        if (!image.naturalWidth || !state) return;
        // Proporção exata da imagem: aceita quebrado (20 × 13,7).
        var rows = state.cols * image.naturalHeight / image.naturalWidth;
        send(urls.config, { rows: Math.max(0.5, Math.round(rows * 100) / 100) });
      }
    });

    function typing() {
      var tag = (document.activeElement || {}).tagName;
      return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
    }

    var ARROWS = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] };
    // Com vários combates na página, o teclado vale só para o último mapa usado.
    panel.addEventListener("pointerdown", function () { window.__lastBoard = panel; }, true);
    document.addEventListener("keydown", function (event) {
      if (!state || !panel.open || typing() || readonly) return;
      if (window.__lastBoard && window.__lastBoard !== panel) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && urls.undo) {
        event.preventDefault();
        send(urls.undo, {});
        return;
      }
      var step = ARROWS[event.key];
      var token = selected && findToken(selected);
      if (!step || !token || token.x === undefined || !token.can_move) return;
      event.preventDefault();  // não rola a página
      placeSelected({ x: token.x + step[0], y: token.y + step[1] });
    });

    boardEl.addEventListener("dblclick", function (event) {
      if (!state || readonly || !state.is_master) return;
      if (drawing && drawing.kind === "poly") { event.preventDefault(); finishPoly(false); return; }
      if (mode === "fog-pick" && selectedShape) {     // duplo clique revela/cobre a sala
        event.preventDefault();
        send(urls.fog, { op: "toggle", id: selectedShape });
      }
    });

    document.addEventListener("keydown", function (event) {
      if (window.__lastBoard && window.__lastBoard !== panel) return;
      if (typing() || readonly || !state) return;
      if (event.key === "Enter" && drawing && drawing.kind === "poly") {
        event.preventDefault();
        finishPoly(false);
        return;
      }
      if (selectedShape && (event.key === "Delete" || event.key === "Backspace")) {
        event.preventDefault();
        var gone = selectedShape;
        selectedShape = null;
        send(urls.fog, { op: "remove", id: gone });
        return;
      }
      if (event.key === "Escape" && drawing) { finishPoly(true); return; }
      if (event.key === "Escape" && mode !== "move") { aiming = null; setMode("move"); render(); return; }
      if (event.key === "Escape" && panel.classList.contains("board-full")) {
        panel.querySelector("[data-board-action=full]").click();
      }
    });

    panel.addEventListener("toggle", function () {
      if (panel.open) refresh(true);
    });

    if (panel.dataset.fit) {
      var resizeTimer = null;
      window.addEventListener("resize", function () {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(render, 150);
      });
    }
    try {
      adopt(JSON.parse(panel.querySelector("[data-board-payload]").textContent));
    } catch (e) {
      refresh(true);
    }
    var owner = panel.closest("[data-encounter-id]");
    if (window.Live && window.Live.enabled && owner) {
      // Novidades do mapa chegam junto com o resto da página (uma requisição só).
      var liveHandle = window.Live.register("board", owner.dataset.encounterId + (view ? "." + view : ""), function (data) {
        if (busy || drag || paint || drawing || aiming) { liveHandle.reset(); return; }
        adopt(data);
      }, { fast: true });
      afterSend = function () { liveHandle.reset(); };
    } else {
      setInterval(refresh, POLL_MS);
      document.addEventListener("visibilitychange", function () { if (!document.hidden) refresh(); });
    }
  });
})();
