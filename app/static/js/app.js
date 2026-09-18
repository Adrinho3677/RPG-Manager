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
