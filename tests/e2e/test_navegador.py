# -*- coding: utf-8 -*-
"""Cenários de mesa de verdade, no navegador: mestre e jogador ao mesmo tempo."""
import re

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import expect  # noqa: E402

pytestmark = pytest.mark.e2e
LIVE = 9000  # a consulta ao vivo roda a cada 3 s: dá folga


def open_panel(page, selector):
    page.eval_on_selector(selector, "el => el.closest('details').open = true")


# ------------------------------------------------------------------- ficha
def test_adicionar_atributo_nao_fica_salvando(people):
    """Regressão: sem edição pendente, "Adicionar" deixava a ficha em "Salvando…"."""
    ana = people("ana_ficha").register()
    ana.create_character("Kian")
    page = ana.page
    open_panel(page, "[name=new_attr_name]")
    page.fill("[name=new_attr_name]", "Coragem")
    page.click("button[value=add_attribute]")
    expect(page.locator(".flash")).to_contain_text("Coragem")
    expect(page.locator("[data-save-state]")).not_to_have_text(re.compile("Salvando"))

    # Com um campo editado e o salvamento ainda pendente.
    page.fill("input[name='attr__for']", "14")
    page.click("[data-tab-button=pericias]")
    open_panel(page, "[name=new_skill_name]")
    page.fill("[name=new_skill_name]", "Culinária")
    page.click("button[value=add_skill]")
    expect(page.locator(".flash")).to_contain_text("Culinária")
    expect(page.locator("input[name='attr__for']")).to_have_value("14")


def test_rolagem_com_sigla_e_vantagem_na_ficha(people):
    ana = people("ana_dados").register()
    ana.create_character("Kian")
    page = ana.page
    # Fora de campanha o painel de dados aparece na primeira rolagem.
    page.locator("[data-roll]").first.click()
    expect(page.locator(".roll-entry")).to_have_count(1)
    page.fill("[data-formula]", "1d20+FOR")
    page.click("[data-manual]")
    expect(page.locator(".roll-entry").first).to_contain_text("FOR(")
    page.click("[data-mode=vantagem]")
    page.locator("[data-roll]").first.click()
    expect(page.locator(".roll-entry").first).to_contain_text("vantagem")


# ----------------------------------------------------------------- combate
@pytest.fixture
def table(people):
    """Mestre + jogadora na mesma campanha, com um PJ e uma criatura."""
    mestre = people("mestre_%d" % id(people)).register()
    ana = people("ana_%d" % id(people)).register()
    camp = mestre.create_campaign("Cripta")
    ana.join(camp, mestre)
    ana.create_character("Kian", camp)
    mestre.create_character("Ghoul", camp, kind="criatura")
    return mestre, ana, camp


def new_encounter(mestre, camp):
    page = mestre.go("/campanhas/%d/combate" % camp)
    page.fill("input[name=name]", "Emboscada")
    page.click("text=Criar rastreador")
    card = page.locator("[data-encounter]").first
    card.locator("[data-action=add-party]").click()
    roster = card.locator("[data-roster]")
    roster.select_option(roster.locator("option", has_text="Ghoul").first.get_attribute("value"))
    card.locator("[data-quantity]").fill("2")
    card.locator("[data-action=add-sheet]").click()
    expect(card.locator(".combatant")).to_have_count(3)
    return page, card


def test_rodadas_iniciativa_e_atrasar_turno(table):
    mestre, ana, camp = table
    page, card = new_encounter(mestre, camp)

    card.locator("[data-action=initiative]").click()
    expect(card.locator("[data-messages]")).to_contain_text("Iniciativa rolada")
    first = card.locator("[data-turn-name]").inner_text()
    assert first.startswith("Vez de")

    turns = []
    for _ in range(3):
        card.locator("[data-action=next]").click()
        turns.append(card.locator("[data-turn-name]").inner_text())
    assert len(set([first] + turns[:2])) == 3          # três combatentes diferentes
    expect(card.locator("[data-round]")).to_have_text("2")  # deu a volta

    # Atrasar: quem está na vez sai da ordem e a vez passa para o próximo.
    current = card.locator(".combatant.turn")
    current.locator(".delay-btn").click()
    expect(card.locator(".combatant.delayed")).to_have_count(1)
    expect(card.locator(".combatant.turn")).not_to_have_class(re.compile("delayed"))

    # A jogadora vê a mesma rodada, ao vivo.
    player = ana.go("/campanhas/%d/combate" % camp)
    expect(player.locator("[data-round]").first).to_have_text("2")


def test_mapa_ao_vivo_teclado_e_desfazer(table):
    mestre, ana, camp = table
    page, card = new_encounter(mestre, camp)
    panel = card.locator("[data-board]")

    # Mestre põe o PJ no mapa: toca na ficha "na mão" e depois num quadrado.
    panel.locator(".bench-token", has_text="Kian").click()
    surface = panel.locator("[data-board-surface]")
    box = surface.bounding_box()
    cell = box["width"] / 20
    surface.click(position={"x": cell * 3.5, "y": cell * 2.5})
    expect(panel.locator(".board-tokens .token")).to_have_count(1)

    # A jogadora vê aparecer sem recarregar e move com o teclado.
    player = ana.go("/campanhas/%d/combate" % camp)
    ppanel = player.locator("[data-board]").first
    token = ppanel.locator(".board-tokens .token")
    expect(token).to_have_count(1, timeout=LIVE)
    token.click()
    player.keyboard.press("ArrowRight")
    player.keyboard.press("ArrowRight")
    expect(panel.locator(".board-tokens .token")).to_have_attribute(
        "style", re.compile(r"translate\(%dpx" % int(round(5 * cell))), timeout=LIVE)

    # Ela desfaz o último passo.
    ppanel.locator("[data-board-action=undo]").click()
    expect(panel.locator(".board-tokens .token")).to_have_attribute(
        "style", re.compile(r"translate\(%dpx" % int(round(4 * cell))), timeout=LIVE)


# ------------------------------------------------------------------ mesa
def test_handout_relogio_e_sussurro(table):
    mestre, ana, camp = table
    player = ana.go("/campanhas/%d" % camp)

    # Relógio criado pelo mestre aparece para a jogadora.
    page = mestre.go("/campanhas/%d" % camp)
    page.fill("[data-clock-create] [name=title]", "O ritual")
    page.click("[data-clock-create] button")
    expect(player.locator(".clock-title")).to_have_text("O ritual", timeout=LIVE)

    # Sussurro da jogadora chega só ao mestre.
    player.locator(".roll-log header").click()
    player.fill("[data-whisper]", "roubo a chave")
    player.click("[data-whisper-send]")
    expect(page.locator(".roll-entry.whisper")).to_contain_text("roubo a chave", timeout=LIVE)

    # Mostrar para a mesa: abre na tela dela.
    notes = mestre.go("/campanhas/%d/anotacoes/nova" % camp)
    notes.fill("#title", "Carta do duque")
    notes.fill("#body", "Traição à meia-noite")
    notes.check("input[name=visibility][value=mestre]")
    notes.click("form button[type=submit]")
    mestre.page.locator("form[action$='/mostrar'] button").first.click()
    expect(player.locator(".handout")).to_contain_text("Carta do duque", timeout=LIVE)
    expect(player.locator(".handout")).to_contain_text("Traição")


def test_tela_da_tv_mostra_so_o_que_a_mesa_ve(table):
    mestre, ana, camp = table
    page, card = new_encounter(mestre, camp)
    panel = card.locator("[data-board]")
    # Um ghoul no mapa, escondido pelo mestre.
    panel.locator(".bench-token", has_text="Ghoul 1").click()
    box = panel.locator("[data-board-surface]").bounding_box()
    panel.locator("[data-board-surface]").click(position={"x": box["width"] / 20 * 5.5, "y": 30})
    expect(panel.locator(".board-tokens .token")).to_have_count(1)
    panel.locator("text=🙈 Esconder").click()  # depois de pôr, a ficha continua selecionada
    expect(panel.locator(".token.is-hidden")).to_have_count(1)

    tv = mestre.context.new_page()  # o próprio mestre abrindo a TV
    tv.goto(mestre.base + "/campanhas/%d/tv" % camp)
    expect(tv.locator(".tv-combatant")).to_have_count(2)  # Kian e Ghoul 2 — o escondido não
    expect(tv.locator(".board-tokens .token")).to_have_count(0)
    tv.close()


def test_tesouro_dividir(table):
    mestre, ana, camp = table
    page = ana.go("/campanhas/%d/tesouro" % camp)
    page.fill("[data-coin=po]", "31")
    page.click("[data-coin-form] button[type=submit]")
    expect(page.locator(".coin-amount").nth(3)).to_have_text("31")
    page.click("[data-split]")
    expect(page.locator("[data-log]")).to_contain_text("dividiu entre Kian")
    expect(page.locator(".coin-amount").nth(3)).to_have_text("0")


def test_painel_de_rolagens_recolhido_nao_cobre_a_tela(table):
    """Regressão: as linhas novas (vantagem, fórmulas, sussurro) apareciam com o painel recolhido."""
    mestre, ana, camp = table
    page = ana.go("/campanhas/%d" % camp)
    panel = page.locator(".roll-log")
    expect(panel).to_have_class(re.compile("collapsed"))
    for part in (".roll-modes", ".roll-help", ".whisper-box", ".roll-secret"):
        expect(panel.locator(part)).to_be_hidden()
    assert panel.bounding_box()["height"] < 70
    panel.locator("header").click()
    expect(panel.locator(".whisper-box")).to_be_visible()



def risco(page, surface, cell, pontos):
    """Arrasta o mouse pelo mapa, em quadrados."""
    box = surface.bounding_box()
    page.mouse.move(box["x"] + cell * pontos[0][0], box["y"] + cell * pontos[0][1])
    page.mouse.down()
    for x, y in pontos[1:]:
        page.mouse.move(box["x"] + cell * x, box["y"] + cell * y, steps=4)
    page.mouse.up()


def test_ajustar_forma_e_area_pelas_alcas(table):
    """Depois de criadas, forma de névoa e área se movem, esticam e giram."""
    mestre, ana, camp = table
    page, card = new_encounter(mestre, camp)
    panel = card.locator("[data-board]")
    encounter_id = card.get_attribute("data-encounter-id")
    estado = lambda: page.evaluate(
        "url => fetch(url).then(r => r.json())",
        "/campanhas/%d/combate/%s/mapa" % (camp, encounter_id))

    panel.locator(".board-config summary").click()
    panel.locator("[data-board-config] [name=fog]").check()
    expect(panel.locator("[data-board-mode=fog-rect]")).to_be_visible()
    surface = panel.locator("[data-board-surface]")
    surface.scroll_into_view_if_needed()
    cell = surface.bounding_box()["width"] / estado()["cols"]

    def arrasta(x0, y0, x1, y1):
        surface.scroll_into_view_if_needed()   # focar um campo da barra rola a página
        box = surface.bounding_box()
        page.mouse.move(box["x"] + cell * x0, box["y"] + cell * y0)
        page.mouse.down()
        page.mouse.move(box["x"] + cell * x1, box["y"] + cell * y1, steps=6)
        page.mouse.up()
        page.wait_for_timeout(700)

    def alca(role):
        """Onde a alça está, em quadrados — lido do próprio SVG."""
        return page.evaluate(
            """role => {
                 const c = document.querySelector('[data-board-handles] [data-handle=' +
                                                  JSON.stringify(role) + ']');
                 return c && [parseFloat(c.getAttribute('cx')), parseFloat(c.getAttribute('cy'))];
               }""", role)

    def forma():
        return estado()["fog_layer"]["shapes"][0]

    panel.locator("[data-board-mode=fog-rect]").click()
    arrasta(3, 3, 8, 6)
    assert forma()["points"] == [[3, 3], [8, 6]]

    # Sem seleção não há alça nenhuma no mapa.
    expect(panel.locator("[data-board-handles] .handle")).to_have_count(0)
    panel.locator("[data-board-mode=fog-pick]").click()
    surface.click(position={"x": cell * 5, "y": cell * 4})
    page.wait_for_timeout(250)   # tem de ser no clique, não no refresh automático
    assert panel.locator("[data-board-handles] .handle").count() == 6

    centro = alca("move")
    arrasta(centro[0], centro[1], centro[0] + 4, centro[1] + 4)
    assert forma()["points"] == [[7, 7], [12, 10]]

    canto = alca("se")
    arrasta(canto[0], canto[1], canto[0] + 3, canto[1] + 2)
    assert forma()["points"] == [[7, 7], [15, 12]]     # largura e altura mudam juntas

    girar, meio = alca("rotate"), alca("move")
    arrasta(girar[0], girar[1], meio[0] + 4, meio[1])   # um quarto de volta
    virada = forma()
    assert virada["kind"] == "poly"                     # retângulo girado vira polígono
    largura = max(p[0] for p in virada["points"]) - min(p[0] for p in virada["points"])
    altura = max(p[1] for p in virada["points"]) - min(p[1] for p in virada["points"])
    assert (round(largura), round(altura)) == (5, 8)    # era 8 × 5

    # Área de efeito: a ponta gira e estica de uma vez.
    panel.locator("[data-area-size]").fill("6")
    panel.locator("[data-area-shape=cone]").click()
    arrasta(4, 11, 7, 11)
    area = estado()["areas"][0]
    assert round(area["angle"]) == 0

    panel.locator(".area-row").first.click()
    expect(panel.locator("[data-board-handles] .handle")).to_have_count(2)
    ponta = alca("area-aim")
    arrasta(ponta[0], ponta[1], area["ox"], area["oy"] + 3)
    virado = estado()["areas"][0]
    assert virado["id"] == area["id"] and len(estado()["areas"]) == 1
    assert round(virado["angle"]) == 90 and virado["size"] == 3


SEM_ROTULO = """() => {
  const faltando = [];
  document.querySelectorAll('input, select, textarea').forEach(el => {
    if (el.type === 'hidden' || el.disabled) return;
    const id = el.getAttribute('id');
    const rotulado = (id && document.querySelector('label[for="' + CSS.escape(id) + '"]')) ||
                     el.closest('label') || el.getAttribute('aria-label') ||
                     el.getAttribute('aria-labelledby') || el.getAttribute('title');
    if (!rotulado) faltando.push(el.tagName.toLowerCase() + '[name=' + (el.name || '?') + ']');
  });
  return faltando;
}"""

ROLAGEM_LATERAL = """() => document.documentElement.scrollWidth - window.innerWidth"""


def test_todo_campo_tem_rotulo_e_nada_rola_de_lado(table):
    """Leitor de tela precisa saber o que é cada campo, e o celular não pode
    rolar de lado. Regressão: a ficha inteira e a tela da TV falhavam nisso."""
    mestre, ana, camp = table
    ficha = ana.create_character("Kian", camp)
    mestre.go("/campanhas/%d/combate" % camp)
    page = mestre.page
    page.fill("input[name=name]", "Emboscada")
    page.click("text=Criar rastreador")

    paginas = ["/painel", "/conta", "/campanhas/%d" % camp,
               "/campanhas/%d/anotacoes" % camp, "/campanhas/%d/sessoes" % camp,
               "/campanhas/%d/combate" % camp, "/campanhas/%d/tesouro" % camp,
               "/campanhas/%d/calendario" % camp, "/campanhas/%d/tabelas" % camp,
               "/campanhas/%d/linha-do-tempo" % camp, "/campanhas/%d/tv" % camp]
    mudos = {}
    for caminho in paginas:
        mestre.go(caminho)
        page.wait_for_timeout(200)
        faltando = page.evaluate(SEM_ROTULO)
        if faltando:
            mudos[caminho] = faltando
    # A ficha é a tela mais usada: dezenas de campos, todos precisam de nome.
    ana.go("/fichas/%d" % ficha)
    ana.page.wait_for_timeout(300)
    faltando = ana.page.evaluate(SEM_ROTULO)
    if faltando:
        mudos["/fichas/%d" % ficha] = faltando
    assert not mudos, "campos sem rótulo: %s" % mudos

    # Celular: nenhuma página pode passar da largura da janela.
    page.set_viewport_size({"width": 375, "height": 812})
    largas = {}
    for caminho in paginas + ["/fichas/%d" % ficha]:
        mestre.go(caminho)
        page.wait_for_timeout(250)
        sobra = page.evaluate(ROLAGEM_LATERAL)
        if sobra > 2:
            largas[caminho] = sobra
    page.set_viewport_size({"width": 1280, "height": 900})
    assert not largas, "páginas que rolam de lado no celular: %s" % largas


def test_trocar_e_soltar_a_forma_de_nevoa(table):
    """Regressão: escolher uma forma só mostrava as alças no refresh seguinte,
    e clicar fora não soltava — dava a impressão de mapa travado."""
    mestre, ana, camp = table
    page, card = new_encounter(mestre, camp)
    panel = card.locator("[data-board]")
    panel.locator(".board-config summary").click()
    panel.locator("[data-board-config] [name=fog]").check()
    expect(panel.locator("[data-board-mode=fog-rect]")).to_be_visible()
    surface = panel.locator("[data-board-surface]")
    surface.scroll_into_view_if_needed()
    encounter_id = card.get_attribute("data-encounter-id")
    cols = page.evaluate("url => fetch(url).then(r => r.json()).then(s => s.cols)",
                         "/campanhas/%d/combate/%s/mapa" % (camp, encounter_id))
    cell = surface.bounding_box()["width"] / cols

    def arrasta(x0, y0, x1, y1):
        surface.scroll_into_view_if_needed()
        box = surface.bounding_box()
        page.mouse.move(box["x"] + cell * x0, box["y"] + cell * y0)
        page.mouse.down()
        page.mouse.move(box["x"] + cell * x1, box["y"] + cell * y1, steps=6)
        page.mouse.up()
        page.wait_for_timeout(600)

    def alcas():
        """Quantas alças estão na tela agora e onde fica a do meio."""
        page.wait_for_timeout(250)
        return page.evaluate("""() => {
            const layer = document.querySelector('[data-board-handles]');
            const meio = layer.querySelector('[data-handle="move"]');
            return [layer.querySelectorAll('.handle').length,
                    meio && [+meio.getAttribute('cx'), +meio.getAttribute('cy')]];
        }""")

    panel.locator("[data-board-mode=fog-rect]").click()
    arrasta(2, 2, 6, 5)          # sala A, centro em 4 × 3,5
    arrasta(10, 2, 15, 6)        # sala B, centro em 12,5 × 4

    panel.locator("[data-board-mode=fog-pick]").click()
    assert alcas() == [0, None]

    def clica(x, y):
        surface.scroll_into_view_if_needed()
        box = surface.bounding_box()
        page.mouse.click(box["x"] + cell * x, box["y"] + cell * y)

    clica(4, 3)
    assert alcas() == [6, [4, 3.5]]          # aparece no clique, não segundos depois
    expect(panel.locator("[data-fog-shape-tools]")).to_be_visible()

    clica(12, 4)
    assert alcas() == [6, [12.5, 4]]         # troca direto para a outra sala

    clica(18, 12)                            # clique no vazio solta
    assert alcas() == [0, None]
    expect(panel.locator("[data-fog-shape-tools]")).to_be_hidden()

    clica(4, 3)
    assert alcas()[0] == 6
    page.keyboard.press("Escape")            # Esc solta e continua em "Selecionar"
    assert alcas() == [0, None]
    expect(panel.locator("[data-board-mode=fog-pick]")).to_have_class(re.compile("active"))

    clica(12, 4)
    panel.locator("[data-board-action=fog-drop]").click()   # e o ✕ da barra também
    assert alcas() == [0, None]


def test_a_mesa_desenha_no_mapa(table):
    """Mestre rabisca o plano, a jogadora vê ao vivo, desenha o dela e apaga."""
    mestre, ana, camp = table
    page, card = new_encounter(mestre, camp)
    panel = card.locator("[data-board]")
    encounter_id = card.get_attribute("data-encounter-id")
    estado = lambda alvo: alvo.evaluate(
        "url => fetch(url).then(r => r.json())",
        "/campanhas/%d/combate/%s/mapa" % (camp, encounter_id))

    surface = panel.locator("[data-board-surface]")
    surface.scroll_into_view_if_needed()
    cell = surface.bounding_box()["width"] / estado(page)["cols"]

    panel.locator("[data-board-mode=draw]").click()
    panel.locator("[data-draw-color]").evaluate(
        "el => { el.value = '#ff5c5c'; el.dispatchEvent(new Event('change', { bubbles: true })); }")
    risco(page, surface, cell, [(3, 3), (6, 4), (9, 3), (11, 6)])
    page.wait_for_timeout(900)
    feito = estado(page)["drawings"]
    assert len(feito) == 1 and feito[0]["color"] == "#ff5c5c"
    assert len(feito[0]["points"]) > 3 and feito[0]["who"] == mestre.name
    expect(panel.locator("[data-board-draw] .drawing")).to_have_count(1)

    # A jogadora recebe o desenho pela mesa ao vivo.
    player = ana.go("/campanhas/%d/combate" % camp)
    expect(player.locator("[data-board-draw] .drawing")).to_have_count(1, timeout=LIVE)

    # E desenha o plano dela.
    painel = player.locator("[data-board]").first
    campo = painel.locator("[data-board-surface]")
    campo.scroll_into_view_if_needed()
    painel.locator("[data-board-mode=draw]").click()
    risco(player, campo, cell, [(13, 8), (15, 10)])
    expect(painel.locator("[data-board-draw] .drawing")).to_have_count(2, timeout=LIVE)
    assert sorted(d["who"] for d in estado(player)["drawings"]) == sorted([mestre.name, ana.name])

    # A borracha dela não encosta no desenho do mestre...
    painel.locator("[data-board-mode=erase]").click()
    caixa = campo.bounding_box()
    player.mouse.click(caixa["x"] + cell * 6, caixa["y"] + cell * 4)
    player.wait_for_timeout(700)
    assert len(estado(player)["drawings"]) == 2

    # ... mas apaga o dela.
    player.mouse.click(caixa["x"] + cell * 14, caixa["y"] + cell * 9)
    expect(painel.locator("[data-board-draw] .drawing")).to_have_count(1, timeout=LIVE)
    assert [d["who"] for d in estado(player)["drawings"]] == [mestre.name]

    # O mestre fecha o desenho: a ferramenta some para ela.
    panel.locator(".board-config summary").click()
    panel.locator("[data-board-config] [name=players_draw]").uncheck()
    expect(painel.locator("[data-draw-tools]")).to_be_hidden(timeout=LIVE)
    expect(panel.locator("[data-draw-tools]")).to_be_visible()


def test_nevoa_pintada_com_o_mouse(table):
    """O pincel manda o traço ao servidor e o jogador só vê o que foi pintado."""
    mestre, ana, camp = table
    page, card = new_encounter(mestre, camp)
    panel = card.locator("[data-board]")

    # Grade quebrada e névoa ligada, pela tela de configurar.
    panel.locator(".board-config summary").click()
    panel.locator("[data-board-config] [name=cols]").fill("18,5")
    panel.locator("[data-board-config] [name=rows]").fill("12,4")
    panel.locator("[data-board-config] [name=rows]").press("Tab")
    panel.locator("[data-board-config] [name=fog]").check()
    expect(panel.locator("[data-board-mode=fog-brush]")).to_be_visible()

    # O número do combate muda conforme os testes anteriores: leia da própria página.
    encounter_id = card.get_attribute("data-encounter-id")
    estado = lambda: page.evaluate(
        "url => fetch(url).then(r => r.json())",
        "/campanhas/%d/combate/%s/mapa" % (camp, encounter_id))
    assert [estado()["cols"], estado()["rows"]] == [18.5, 12.4]

    # Põe o ghoul no mapa e pinta um traço longe dele.
    panel.locator(".bench-token", has_text="Ghoul 1").click()
    surface = panel.locator("[data-board-surface]")
    box = surface.bounding_box()
    cell = box["width"] / 18.5
    surface.click(position={"x": cell * 3.5, "y": cell * 3.5})
    expect(panel.locator(".board-tokens .token")).to_have_count(1)

    # Névoa por formas: a caixinha "corta" faz a forma nova abrir buraco.
    panel.locator("[data-fog-cut]").check()
    panel.locator("[data-board-mode=fog-brush]").click()
    # Mede o mapa na hora e pinta perto do topo: coordenada do mouse é da janela,
    # e pôr a ficha mudou a altura da barra acima do mapa.
    surface.scroll_into_view_if_needed()
    box = surface.bounding_box()
    page.mouse.move(box["x"] + cell * 12, box["y"] + cell * 2)
    page.mouse.down()
    for step in range(6):
        page.mouse.move(box["x"] + cell * (12 + step * 0.4), box["y"] + cell * (2 + step * 0.3))
    page.mouse.up()
    page.wait_for_timeout(1200)
    layer = estado()["fog_layer"]
    assert layer["fill"] is True and len(layer["shapes"]) == 1
    assert layer["shapes"][0]["kind"] == "brush" and layer["shapes"][0]["cut"] is True
    assert len(layer["shapes"][0]["points"]) > 1

    # O ghoul está fora da forma cortada: a jogadora não o vê.
    player = ana.go("/campanhas/%d/combate" % camp)
    expect(player.locator("[data-board] .board-tokens .token")).to_have_count(0, timeout=LIVE)

    # Cortando em cima dele, aparece.
    box = surface.bounding_box()
    page.mouse.move(box["x"] + cell * 4, box["y"] + cell * 3.5)
    page.mouse.down()
    page.mouse.move(box["x"] + cell * 4.2, box["y"] + cell * 3.6)
    page.mouse.up()
    expect(player.locator("[data-board] .board-tokens .token")).to_have_count(1, timeout=LIVE)

    # Fim da cena: seleciona a forma e manda cobrir de novo — sem redesenhar.
    panel.locator("[data-board-mode=fog-pick]").click()
    surface.click(position={"x": cell * 4.1, "y": cell * 3.55})
    expect(panel.locator("[data-fog-shape-tools]")).to_be_visible()
    panel.locator("[data-board-action=fog-uncut]").click()
    expect(player.locator("[data-board] .board-tokens .token")).to_have_count(0, timeout=LIVE)
