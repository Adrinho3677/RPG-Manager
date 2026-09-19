/* Tela da TV: ordem de iniciativa e últimas rolagens, ao vivo.

   O mapa (board.js, só leitura) e os relógios (clocks.js) se atualizam
   sozinhos; aqui ficam a ordem de iniciativa e o registro de rolagens. Tudo
   pedido na "visão da mesa" (".mesa"): o que os jogadores veem, mesmo que
   quem está logado na TV seja o mestre.
*/
(function () {
  "use strict";

  var root = document.querySelector("[data-tv-root]");
  if (!root) return;
  document.body.classList.add("tv-mode");

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  /* ------------------------------------------------------ iniciativa */
  var order = root.querySelector("[data-tv-order]");
  var turnBox = root.querySelector("[data-tv-turn]");
  function renderOrder(state) {
    if (!order || !state) return;
    order.innerHTML = "";
    var current = null;
    (state.combatants || []).forEach(function (c, index) {
      var item = el("li", "tv-combatant kind-" + (c.kind || "criatura") +
                          (index === state.turn_index ? " is-turn" : "") + (c.delayed ? " is-delayed" : ""));
      item.appendChild(el("strong", "", c.name || "?"));
      if (c.hp !== undefined && c.kind === "pj") {
        item.appendChild(el("span", "tv-hp", c.hp + "/" + c.hp_max));
      } else if (c.health) {
        item.appendChild(el("span", "tag", c.health));
      }
      if (c.delayed) item.appendChild(el("span", "tag tag-gold", "aguardando"));
      (c.conditions || []).forEach(function (cond) {
        item.appendChild(el("span", "tag tag-danger", cond.name));
      });
      order.appendChild(item);
      if (index === state.turn_index) current = c;
    });
    var round = root.querySelector("[data-tv-round]");
    if (round) round.textContent = state.round_number;
    if (turnBox) turnBox.textContent = current ? "Vez de " + current.name : "";
  }
  var stateNode = root.querySelector("[data-tv-state]");
  if (stateNode) {
    try { renderOrder(JSON.parse(stateNode.textContent)); } catch (e) {}
  }

  /* -------------------------------------------------------- rolagens */
  var rolls = root.querySelector("[data-tv-rolls]");
  var seen = {};
  function addRoll(roll) {
    if (seen[roll.id]) return;
    seen[roll.id] = true;
    var line = el("div", "tv-roll" + (roll.flag ? " " + roll.flag : ""));
    line.appendChild(el("span", "tv-roll-who", roll.who || ""));
    line.appendChild(el("span", "tv-roll-label", roll.label));
    line.appendChild(el("strong", "tv-roll-result", roll.result));
    rolls.insertBefore(line, rolls.firstChild);
    while (rolls.children.length > 8) rolls.removeChild(rolls.lastChild);
    line.classList.add("is-new");
    setTimeout(function () { line.classList.remove("is-new"); }, 4000);
  }

  if (window.Live && window.Live.enabled) {
    if (root.dataset.encounterId) {
      window.Live.register("enc", root.dataset.encounterId + ".mesa", renderOrder, { fast: true });
    }
    window.Live.register("rolls", "mesa", function (items) { (items || []).forEach(addRoll); }, { fast: true });
  }

  /* ---------------------------------------------------------- controles */
  var choose = root.querySelector("[data-tv-choose]");
  if (choose) choose.addEventListener("change", function () { location.href = choose.value; });
  var full = root.querySelector("[data-tv-full]");
  if (full) {
    full.addEventListener("click", function () {
      if (document.fullscreenElement) document.exitFullscreen();
      else if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen();
    });
  }
})();
