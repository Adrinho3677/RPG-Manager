/* Tesouro do grupo: moedas, itens, divisão e registro.

   Qualquer um da mesa mexe; o servidor aplica cada operação sobre o valor mais
   novo (não perde a mudança de outra pessoa) e devolve o tesouro atualizado.
   As mudanças dos outros chegam pela consulta única (window.Live).
*/
(function () {
  "use strict";

  var root = document.querySelector("[data-treasure]");
  if (!root) return;

  var state;
  try { state = JSON.parse(root.querySelector("[data-treasure-payload]").textContent); } catch (e) { return; }
  var status = root.querySelector("[data-treasure-status]");
  var chosen = {};  // quem entra na divisão (id -> true)
  state.party.forEach(function (p) { chosen[p.id] = true; });

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function coinLabel(coin) { return coin.abbr || coin.name; }
  function number(value) { return Number(String(value || "").replace(",", ".")) || 0; }
  function pretty(value) {
    var n = Math.round(value * 100) / 100;
    return String(n).replace(".", ",");
  }

  function send(body) {
    status.textContent = "salvando…";
    status.dataset.kind = "saving";
    return window.api(root.dataset.url, { body: body }).then(function (data) {
      if (!data.ok) {
        status.textContent = data.message || "não deu certo";
        status.dataset.kind = "error";
        return false;
      }
      status.textContent = "salvo ✓";
      status.dataset.kind = "saved";
      adopt(data.treasure);
      if (window.Live) window.Live.poke();
      return true;
    }).catch(function () {
      status.textContent = "sem conexão";
      status.dataset.kind = "error";
      return false;
    });
  }

  /* ------------------------------------------------------------ moedas */
  function renderCoins() {
    var grid = root.querySelector("[data-coins]");
    grid.innerHTML = "";
    state.coins.forEach(function (coin) {
      var box = el("div", "coin");
      box.appendChild(el("span", "coin-amount", String(coin.amount)));
      box.appendChild(el("span", "coin-name", coinLabel(coin)));
      box.title = coin.name;
      grid.appendChild(box);
    });
    var inputs = root.querySelector("[data-coin-inputs]");
    if (!inputs.children.length) {
      state.coins.forEach(function (coin) {
        var label = el("label", "coin-input");
        var input = el("input");
        input.type = "number";
        input.name = "coin_" + coin.key;
        input.dataset.coin = coin.key;
        input.placeholder = "0";
        input.setAttribute("aria-label", coin.name);
        label.appendChild(input);
        label.appendChild(el("span", "muted small", coinLabel(coin)));
        inputs.appendChild(label);
      });
    }
  }

  root.querySelector("[data-coin-form]").addEventListener("submit", function (event) {
    event.preventDefault();
    var form = event.target, deltas = {}, any = false;
    form.querySelectorAll("[data-coin]").forEach(function (input) {
      var value = parseInt(input.value, 10);
      if (value) { deltas[input.dataset.coin] = value; any = true; }
    });
    if (!any) return;
    var reason = form.elements["reason"];
    send({ op: "coins", deltas: deltas, reason: reason.value }).then(function (ok) {
      if (!ok) return;
      form.querySelectorAll("[data-coin]").forEach(function (input) { input.value = ""; });
      reason.value = "";
    });
  });

  /* ------------------------------------------------------------ divisão */
  function renderSplit() {
    var box = root.querySelector("[data-split-people]");
    box.innerHTML = "";
    if (!state.party.length) {
      box.appendChild(el("p", "muted small", "Nenhum personagem de jogador na campanha ainda."));
    }
    state.party.forEach(function (person) {
      var label = el("label", "check");
      var check = el("input");
      check.type = "checkbox";
      check.checked = !!chosen[person.id];
      check.addEventListener("change", function () { chosen[person.id] = check.checked; renderPreview(); });
      label.appendChild(check);
      label.appendChild(document.createTextNode(" " + person.name));
      box.appendChild(label);
    });
    renderPreview();
  }

  function people() {
    return state.party.filter(function (p) { return chosen[p.id]; });
  }

  function renderPreview() {
    var preview = root.querySelector("[data-split-preview]");
    var n = people().length;
    if (!n) { preview.textContent = "Marque quem entra na divisão."; return; }
    var parts = state.coins.filter(function (c) { return c.amount; }).map(function (coin) {
      var each = Math.floor(coin.amount / n), left = coin.amount - each * n;
      return each + " " + coinLabel(coin) + (left ? " (sobra " + left + ")" : "");
    });
    preview.textContent = parts.length ? "Cada um recebe: " + parts.join(" · ") : "O tesouro está sem moedas.";
  }

  root.querySelector("[data-split]").addEventListener("click", function () {
    var list = people();
    if (!list.length) return;
    var names = list.map(function (p) { return p.name; }).join(", ");
    if (!confirm("Dividir as moedas entre " + names + "? As partes saem do tesouro; cada um anota a sua na ficha.")) return;
    send({ op: "split", characters: list.map(function (p) { return p.id; }) });
  });

  /* ------------------------------------------------------------- itens */
  function renderItems() {
    var box = root.querySelector("[data-items]");
    box.innerHTML = "";
    root.querySelector("[data-weight]").textContent = state.weight
      ? "peso total " + pretty(state.weight) + (state.unit ? " " + state.unit : "") : "";
    if (!state.items.length) {
      box.appendChild(el("p", "muted small", "Nada guardado ainda."));
      return;
    }
    state.items.forEach(function (item) {
      var row = el("div", "treasure-item");
      var main = el("div", "treasure-item-main");
      main.appendChild(el("strong", "", item.name));
      var meta = [];
      if (item.weight) meta.push(pretty(item.weight) + (state.unit ? " " + state.unit : "") + " cada");
      if (item.value) meta.push(item.value);
      if (item.note) meta.push(item.note);
      if (meta.length) main.appendChild(el("span", "muted small", meta.join(" · ")));
      row.appendChild(main);

      var qty = el("input");
      qty.type = "number";
      qty.min = "0";
      qty.value = item.qty;
      qty.className = "treasure-qty";
      qty.setAttribute("aria-label", "Quantidade de " + item.name);
      qty.addEventListener("change", function () {
        send({ op: "update_item", id: item.id, qty: qty.value });
      });
      row.appendChild(qty);

      if (state.party.length) {
        var give = el("select", "treasure-give");
        give.setAttribute("aria-label", "Entregar " + item.name);
        var first = el("option", "", "Entregar a…");
        first.value = "";
        give.appendChild(first);
        state.party.forEach(function (person) {
          var option = el("option", "", person.name);
          option.value = person.id;
          give.appendChild(option);
        });
        give.addEventListener("change", function () {
          if (!give.value) return;
          var person = state.party.filter(function (p) { return String(p.id) === give.value; })[0];
          var how = item.qty > 1 ? prompt("Quantos " + item.name + " para " + person.name + "?", "1") : "1";
          if (how === null) { give.value = ""; return; }
          send({ op: "give_item", id: item.id, to: person.id, qty: parseInt(how, 10) || 1 });
        });
        row.appendChild(give);
      }

      var remove = el("button", "btn btn-ghost btn-sm btn-icon", "✕");
      remove.type = "button";
      remove.title = "Tirar do tesouro";
      remove.addEventListener("click", function () {
        if (confirm("Tirar “" + item.name + "” do tesouro?")) send({ op: "remove_item", id: item.id });
      });
      row.appendChild(remove);
      box.appendChild(row);
    });
  }

  root.querySelector("[data-item-form]").addEventListener("submit", function (event) {
    event.preventDefault();
    var f = event.target.elements;
    send({ op: "add_item", name: f["name"].value, qty: f["qty"].value,
           weight: number(f["weight"].value), value: f["value"].value }).then(function (ok) {
      if (!ok) return;
      f["name"].value = "";
      f["qty"].value = "1";
      f["weight"].value = "";
      f["value"].value = "";
      f["name"].focus();
    });
  });

  /* ---------------------------------------------------------- registro */
  function renderLog() {
    var box = root.querySelector("[data-log]");
    box.innerHTML = "";
    if (!state.log.length) {
      box.appendChild(el("p", "muted small", "Nenhuma movimentação ainda."));
      return;
    }
    state.log.forEach(function (entry) {
      var line = el("div", "treasure-log-line");
      var when = "";
      var parsed = new Date(entry.at);
      if (!isNaN(parsed)) {
        when = parsed.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit",
                                                hour: "2-digit", minute: "2-digit" });
      }
      line.appendChild(el("span", "muted small", when));
      line.appendChild(el("strong", "", entry.who));
      line.appendChild(el("span", "", entry.text));
      box.appendChild(line);
    });
  }

  function adopt(data) {
    state = data;
    state.party.forEach(function (p) { if (chosen[p.id] === undefined) chosen[p.id] = true; });
    renderCoins();
    renderSplit();
    renderItems();
    renderLog();
  }

  if (window.Live && window.Live.enabled) {
    var handle = window.Live.register("treasure", "", function (data) {
      // Não redesenha embaixo de quem está digitando uma quantidade.
      if (root.contains(document.activeElement) && document.activeElement.tagName !== "BUTTON") {
        handle.reset();
        return;
      }
      adopt(data);
    });
  }
  adopt(state);
})();
