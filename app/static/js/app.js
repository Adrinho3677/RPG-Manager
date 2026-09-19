/* Comportamentos gerais da interface e o cliente HTTP usado por todo o JS. */
(function (global) {
  "use strict";

  var tokenMeta = document.querySelector('meta[name="csrf-token"]');

  /* Toda chamada ao servidor passa por aqui: leva o token CSRF e se identifica
     como fetch, para o servidor responder JSON em vez de redirecionar. */
  function api(url, options) {
    options = options || {};
    var headers = Object.assign({
      "X-Requested-With": "fetch",
      "X-CSRFToken": tokenMeta ? tokenMeta.content : ""
    }, options.headers || {});

    var body = options.body;
    if (body && !(body instanceof FormData) && typeof body !== "string") {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }

    return fetch(url, {
      method: options.method || (body ? "POST" : "GET"),
      headers: headers,
      body: body,
      credentials: "same-origin",
      keepalive: !!options.keepalive
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        data.__status = response.status;
        return data;
      });
    });
  }

  global.api = api;

  /* Confirmações ("Excluir esta ficha?") vêm de data-confirm, nunca de um
     onsubmit="confirm('{{ nome }}')": ali o nome escolhido por um jogador
     viraria código rodando no navegador do mestre. Fase de captura: roda antes
     dos outros tratadores de submit (ex.: o "desfazer" da ficha). */
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (form.dataset && form.dataset.confirm && !form.dataset.confirmed && !confirm(form.dataset.confirm)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  /* ------------------------------------------------ consulta única ao vivo
     Cada parte da página que precisa de novidades (rolagens, rastreador, mapa,
     relógios, handouts, tesouro, a própria ficha) se registra aqui, e uma só
     requisição periódica busca tudo — ver app/blueprints/live.py. Seções que
     não mudaram voltam como {same: true} e não redesenham nada. */
  var Live = (function () {
    var url = document.body.dataset.liveUrl;
    var sections = {};
    var timer = null, inflight = false, failures = 0;
    var FAST_MS = 3000, SLOW_MS = 6000;

    function register(name, arg, onData, options) {
      options = options || {};
      var key = name + ":" + (arg === undefined || arg === null ? "" : arg);
      var section = sections[key] = sections[key] || { name: name, arg: arg, mark: "", handlers: [] };
      if (options.mark !== undefined) section.mark = String(options.mark);
      if (options.fast) section.fast = true;
      section.handlers.push(onData);
      if (url) schedule(50);
      return {
        reset: function () { section.mark = ""; },
        setMark: function (mark) { section.mark = String(mark); }
      };
    }

    function interval() {
      for (var key in sections) if (sections[key].fast) return FAST_MS;
      return SLOW_MS;
    }

    function schedule(wait) {
      clearTimeout(timer);
      timer = setTimeout(tick, wait === undefined ? interval() * Math.min(8, Math.pow(2, failures)) : wait);
    }

    function tick() {
      var keys = Object.keys(sections);
      if (!url || !keys.length) return;
      if (document.hidden || inflight) return schedule();
      inflight = true;
      var spec = keys.map(function (key) {
        var s = sections[key];
        return s.name + ":" + (s.arg === undefined || s.arg === null ? "" : s.arg) + ":" + s.mark;
      }).join(",");
      api(url + "?s=" + encodeURIComponent(spec)).then(function (data) {
        inflight = false;
        failures = data.ok ? 0 : failures + 1;
        Object.keys((data && data.sections) || {}).forEach(function (key) {
          var result = data.sections[key], section = sections[key];
          if (!section || !result || result.same) return;
          if (result.mark !== undefined) section.mark = String(result.mark);
          section.handlers.forEach(function (handler) {
            try { handler(result.data); } catch (e) { if (global.console) console.error(e); }
          });
        });
        schedule();
      }).catch(function () {
        inflight = false;
        failures += 1;
        schedule();
      });
    }

    document.addEventListener("visibilitychange", function () {
      if (!document.hidden && url) schedule(100);
    });

    return {
      enabled: !!url,
      register: register,
      poke: function () { if (url) schedule(150); },   // "busque já" (depois de uma ação minha)
      userId: Number(document.body.dataset.userId || 0),
      campaignId: Number(document.body.dataset.campaignId || 0)
    };
  })();
  global.Live = Live;

  /* ------------------------------------------------ "Mostrar para a mesa"
     O mestre abre uma imagem ou anotação e ela aparece na tela de todos. */
  if (Live.enabled) {
    var SEEN_KEY = "grimorio-spot-" + Live.campaignId;
    var seen = 0;
    try { seen = Number(localStorage.getItem(SEEN_KEY)) || 0; } catch (e) {}

    var showHandout = function (data) {
      var old = document.querySelector(".handout");
      if (old) old.remove();
      var box = document.createElement("div");
      box.className = "handout";
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-modal", "true");
      box.innerHTML = '<div class="handout-card"><header><span class="handout-kicker">📣 O mestre mostrou</span>' +
        '<button class="btn btn-ghost btn-sm btn-icon" type="button" data-close title="Fechar">✕</button></header>' +
        '<h2></h2><div class="handout-body"></div></div>';
      box.querySelector("h2").textContent = data.title || "";
      var body = box.querySelector(".handout-body");
      if (data.image) {
        var img = document.createElement("img");
        img.src = data.image;
        img.alt = data.title || "";
        body.appendChild(img);
      } else {
        body.innerHTML = data.html || "";  // já vem escapado do servidor (rich_text)
        body.classList.add("prose");
      }
      var close = function () { box.remove(); document.removeEventListener("keydown", onKey); };
      var onKey = function (event) { if (event.key === "Escape") close(); };
      box.addEventListener("click", function (event) {
        if (event.target === box || event.target.closest("[data-close]")) close();
      });
      document.addEventListener("keydown", onKey);
      document.body.appendChild(box);
      box.querySelector("[data-close]").focus();
    };

    Live.register("spot", "", function (data) {
      if (!data || data.seq <= seen) return;
      seen = data.seq;
      try { localStorage.setItem(SEEN_KEY, String(seen)); } catch (e) {}
      if (data.by === Live.userId) return;  // quem mostrou já está vendo
      showHandout(data);
    }, { mark: seen || "" });
  }

  // Abas que rolam para o lado: deixa a ativa à vista (sem mexer na rolagem da página).
  function centerActive(bar) {
    var active = bar.querySelector(".active");
    if (!active || bar.scrollWidth <= bar.clientWidth) return;
    bar.scrollLeft = active.offsetLeft - (bar.clientWidth - active.offsetWidth) / 2;
  }
  document.querySelectorAll(".tabs, .sheet-tabs").forEach(function (bar) {
    centerActive(bar);
    bar.addEventListener("click", function () { setTimeout(function () { centerActive(bar); }, 0); });
  });

  // Botões "copiar": copiam o valor de data-copy.
  document.querySelectorAll("[data-copy]").forEach(function (button) {
    button.addEventListener("click", function () {
      var original = button.textContent;
      var done = function () {
        button.textContent = "Copiado ✓";
        setTimeout(function () { button.textContent = original; }, 1500);
      };
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(button.dataset.copy).then(done, function () {});
      } else {
        // http sem TLS (ex.: rede local) não tem clipboard API: seleciona o campo ao lado.
        var field = button.parentElement.querySelector("input");
        if (field) { field.select(); document.execCommand("copy"); done(); }
      }
    });
  });
  document.querySelectorAll("[data-select-all]").forEach(function (field) {
    field.addEventListener("focus", function () { field.select(); });
  });

  // Mensagens somem sozinhas depois de um tempo.
  document.querySelectorAll(".flash").forEach(function (flash) {
    setTimeout(function () {
      flash.style.transition = "opacity .4s";
      flash.style.opacity = "0";
      setTimeout(function () { flash.remove(); }, 400);
    }, 6000);
  });

  // Clicar no código de convite copia para a área de transferência.
  document.querySelectorAll(".code-pill").forEach(function (pill) {
    pill.style.cursor = "pointer";
    pill.title = "Clique para copiar";
    pill.addEventListener("click", function () {
      var text = pill.textContent.trim();
      var done = function () {
        var original = pill.textContent;
        pill.textContent = "copiado!";
        setTimeout(function () { pill.textContent = original; }, 1200);
      };
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(done, function () {});
      }
    });
  });
})(window);
