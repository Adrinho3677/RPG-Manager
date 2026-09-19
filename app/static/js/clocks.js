/* Relógios de progresso: "o ritual se completa em 6 segmentos".

   Aparece em qualquer [data-clocks] (visão geral e combate). O mestre cria,
   preenche (clique no segmento, ou − / +), renomeia, esconde e apaga; a mesa
   vê cada segmento encher ao vivo, pela consulta única (window.Live).
*/
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function wedge(index, total, radius) {
    // Segmento de pizza começando no topo, sentido horário, com uma fresta.
    var gap = total > 1 ? 0.025 : 0;
    var a0 = (index / total) * Math.PI * 2 - Math.PI / 2 + gap;
    var a1 = ((index + 1) / total) * Math.PI * 2 - Math.PI / 2 - gap;
    var large = a1 - a0 > Math.PI ? 1 : 0;
    if (total === 1) {
      var c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", 50); c.setAttribute("cy", 50); c.setAttribute("r", radius);
      return c;
    }
    var path = document.createElementNS(NS, "path");
    path.setAttribute("d", "M50,50 L" + (50 + radius * Math.cos(a0)).toFixed(2) + "," +
      (50 + radius * Math.sin(a0)).toFixed(2) + " A" + radius + "," + radius + " 0 " + large + " 1 " +
      (50 + radius * Math.cos(a1)).toFixed(2) + "," + (50 + radius * Math.sin(a1)).toFixed(2) + " Z");
    return path;
  }

  document.querySelectorAll("[data-clocks]").forEach(function (root) {
    var isMaster = root.dataset.master === "1";
    var list = root.querySelector("[data-clock-list]");
    var createForm = root.querySelector("[data-clock-create]");
    var status = root.querySelector("[data-clock-status]");
    var clocks = [];
    try { clocks = JSON.parse(root.querySelector("[data-clock-payload]").textContent) || []; } catch (e) {}

    function setStatus(text) { if (status) status.textContent = text || ""; }

    function send(url, body) {
      setStatus("salvando…");
      return window.api(url, { body: body }).then(function (data) {
        if (!data.ok) { setStatus(data.message || "não deu certo"); return; }
        setStatus("");
        clocks = data.clocks || [];
        render();
        if (window.Live) window.Live.poke();
      }).catch(function () { setStatus("sem conexão"); });
    }

    function update(clock, body) {
      return send(root.dataset.updateUrl.replace(/0$/, String(clock.id)), body);
    }

    function clockNode(clock) {
      var card = el("div", "clock" + (clock.visibility === "mestre" ? " is-secret" : "") +
                              (clock.filled >= clock.segments ? " is-full" : ""));
      card.style.setProperty("--clock-color", clock.color || "#f0a94b");
      var svg = document.createElementNS(NS, "svg");
      svg.setAttribute("viewBox", "0 0 100 100");
      svg.setAttribute("class", "clock-face");
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", clock.title + ": " + clock.filled + " de " + clock.segments);
      for (var i = 0; i < clock.segments; i++) {
        var piece = wedge(i, clock.segments, 46);
        piece.setAttribute("class", "clock-seg" + (i < clock.filled ? " on" : ""));
        if (isMaster) {
          (function (index) {
            piece.addEventListener("click", function () {
              // Clicar no último preenchido esvazia ele; em outro, enche até ali.
              update(clock, { filled: clock.filled === index + 1 ? index : index + 1 });
            });
          })(i);
        }
        svg.appendChild(piece);
      }
      card.appendChild(svg);

      var body = el("div", "clock-body");
      body.appendChild(el("strong", "clock-title", clock.title));
      body.appendChild(el("span", "clock-count", clock.filled + " / " + clock.segments +
        (clock.filled >= clock.segments ? " · completo!" : "")));
      if (clock.visibility === "mestre") body.appendChild(el("span", "tag tag-danger", "só mestre"));

      if (isMaster) {
        var tools = el("div", "clock-tools");
        [["−", -1, "Esvaziar um"], ["+", 1, "Encher um"]].forEach(function (b) {
          var button = el("button", "btn btn-ghost btn-sm btn-icon", b[0]);
          button.type = "button";
          button.title = b[2];
          button.addEventListener("click", function () { update(clock, { delta: b[1] }); });
          tools.appendChild(button);
        });
        var rename = el("button", "btn btn-ghost btn-sm btn-icon", "✎");
        rename.type = "button";
        rename.title = "Renomear";
        rename.addEventListener("click", function () {
          var title = prompt("Nome do relógio", clock.title);
          if (title && title.trim()) update(clock, { title: title.trim() });
        });
        tools.appendChild(rename);
        var eye = el("button", "btn btn-ghost btn-sm btn-icon", clock.visibility === "mestre" ? "👁" : "🙈");
        eye.type = "button";
        eye.title = clock.visibility === "mestre" ? "Mostrar para a mesa" : "Esconder da mesa";
        eye.addEventListener("click", function () {
          update(clock, { visibility: clock.visibility === "mestre" ? "mesa" : "mestre" });
        });
        tools.appendChild(eye);
        var remove = el("button", "btn btn-ghost btn-sm btn-icon", "✕");
        remove.type = "button";
        remove.title = "Apagar";
        remove.addEventListener("click", function () {
          if (confirm("Apagar o relógio “" + clock.title + "”?")) update(clock, { delete: true });
        });
        tools.appendChild(remove);
        body.appendChild(tools);
      }
      card.appendChild(body);
      return card;
    }

    function render() {
      list.innerHTML = "";
      if (!clocks.length) {
        list.appendChild(el("p", "muted small", isMaster
          ? "Nenhum relógio. Crie um para marcar o que está para acontecer."
          : "Nenhum relógio correndo."));
        return;
      }
      clocks.forEach(function (clock) { list.appendChild(clockNode(clock)); });
    }

    if (createForm) {
      createForm.addEventListener("submit", function (event) {
        event.preventDefault();
        var data = {};
        createForm.querySelectorAll("[name]").forEach(function (f) { data[f.name] = f.value; });
        send(root.dataset.createUrl, data).then(function () {
          var title = createForm.querySelector("[name=title]");
          if (title) title.value = "";
        });
      });
    }

    if (window.Live && window.Live.enabled) {
      window.Live.register("clocks", "", function (data) {
        clocks = data || [];
        render();
      });
    }
    render();
  });
})();
