# -*- coding: utf-8 -*-
"""Linha do tempo e calendário: horas no mundo, ordenação e edição."""
import re

import pytest

from app import worldcal
from app.models import Campaign, GameSession, TimelineEntry


@pytest.fixture
def campanha(mesa):
    camp, code = mesa.campaign("mestre")
    mesa.join("ana", code)
    mestre = mesa.user("mestre")
    mestre.post("/campanhas/%d/calendario" % camp, data={"action": "setup", "preset": "gregoriano",
                                                        "year": "1492", "era": "DR"})
    return camp


def registrar(client, camp, title, day=None, time=""):
    data = {"title": title}
    if day:
        data.update(world_day=str(day), world_month="1", world_year="1492", world_time=time)
    return client.post("/campanhas/%d/linha-do-tempo" % camp, data=data)


def titulos(page):
    """Títulos dos acontecimentos, na ordem da página (sem o formulário ao lado)."""
    return re.findall(r'<h3>([^<]+)</h3>', page.split('class="timeline"')[1].split("<aside")[0])


def test_horas_no_mundo():
    assert worldcal.parse_time("14:30") == 870 and worldcal.parse_time("7h") == 420
    for bad in ("24:00", "9:75", "meio-dia"):
        with pytest.raises(worldcal.CalendarError):
            worldcal.parse_time(bad)
    cal = worldcal.from_preset("gregoriano", "", 1492)
    cal["minute"] = 22 * 60
    worldcal.advance(cal, hours=5)  # passa da meia-noite
    assert worldcal.format_date(cal, cal["today"], False, cal["minute"]) == "2 de Janeiro de 1492, 03:00"


def test_acontecimento_com_hora_e_ordem(campanha, mesa):
    mestre = mesa.user("mestre")
    registrar(mestre, campanha, "Ceia", 3, "20:00")
    registrar(mestre, campanha, "Alvorada", 3, "06:15")
    registrar(mestre, campanha, "Chegada", 1)
    registrar(mestre, campanha, "Sem data")
    url = "/campanhas/%d/linha-do-tempo" % campanha

    page = mestre.get(url).get_data(as_text=True)
    assert titulos(page) == ["Ceia", "Alvorada", "Chegada", "Sem data"]   # história, recente primeiro
    assert "3 de Janeiro de 1492 DR, 20:00" in page
    assert titulos(mestre.get(url + "?ordem=historia_asc").get_data(as_text=True)) == \
        ["Chegada", "Alvorada", "Ceia", "Sem data"]
    assert titulos(mestre.get(url + "?ordem=registro").get_data(as_text=True)) == \
        ["Sem data", "Chegada", "Alvorada", "Ceia"]
    # A escolha fica lembrada.
    assert titulos(mestre.get(url).get_data(as_text=True))[0] == "Sem data"
    # Ordem inválida não quebra.
    assert mestre.get(url + "?ordem=xyz").status_code == 200


def test_hora_sem_data_ou_invalida(campanha, mesa):
    mestre = mesa.user("mestre")
    bad = mestre.post("/campanhas/%d/linha-do-tempo" % campanha,
                      data={"title": "X", "world_time": "10:00"}, follow_redirects=True)
    assert "Informe a data junto com a hora" in bad.get_data(as_text=True)
    bad = registrar(mestre, campanha, "Y", 2, "25:00")
    with mesa.app.app_context():
        assert TimelineEntry.query.count() == 0


def test_editar_acontecimento(campanha, mesa, app):
    ana, mestre = mesa.user("ana"), mesa.user("mestre")
    registrar(ana, campanha, "Duelo", 5, "15:00")
    with app.app_context():
        entry_id = TimelineEntry.query.one().id
    url = "/campanhas/%d/linha-do-tempo/%d/editar" % (campanha, entry_id)

    page = ana.get(url).get_data(as_text=True)
    assert 'value="Duelo"' in page and 'value="15:00"' in page
    ana.post(url, data={"title": "Duelo ao amanhecer", "body": "Kian venceu", "world_day": "6",
                        "world_month": "1", "world_year": "1492", "world_time": "05:30"})
    with app.app_context():
        entry = TimelineEntry.query.one()
        assert (entry.title, entry.body, entry.world_minute) == ("Duelo ao amanhecer", "Kian venceu", 330)
        assert worldcal.from_ordinal(worldcal.normalize(entry.campaign.calendar), entry.world_day) == (1492, 1, 6)
        assert entry.updated_at is not None

    # Mestre também edita; quem não escreveu nem é mestre, não.
    mestre.post(url, data={"title": "Duelo", "world_day": "", "world_month": "", "world_year": ""})
    with app.app_context():
        assert TimelineEntry.query.one().world_day is None  # tirou a data
    mesa.join("bia", mesa.get(Campaign, campanha).invite_code)
    assert mesa.user("bia").get(url).status_code == 403
    assert mesa.user("bia").post(url, data={"title": "hack"}).status_code == 403
    assert mestre.post(url, data={"title": " "}, follow_redirects=True).status_code == 200
    with app.app_context():
        assert TimelineEntry.query.one().title == "Duelo"


def test_calendario_ordena_por_hora_e_lista_do_mes(campanha, mesa, app):
    mestre = mesa.user("mestre")
    registrar(mestre, campanha, "Ceia", 3, "20:00")
    registrar(mestre, campanha, "Alvorada", 3, "06:15")
    registrar(mestre, campanha, "Sem hora", 3)
    mestre.post("/campanhas/%d/sessoes/nova" % campanha, data={"title": "Viagem"})
    with app.app_context():
        sid = GameSession.query.one().id
    mestre.post("/campanhas/%d/sessoes/%d" % (campanha, sid), data={
        "title": "Viagem", "world_day": "3", "world_month": "1", "world_year": "1492", "world_time": "12:00"})

    url = "/campanhas/%d/calendario?ano=1492&mes=1" % campanha
    page = mestre.get(url).get_data(as_text=True)
    cell = page.split('calendar-agenda"')[0]
    order = [t for t in re.findall(r'calendar-event[^>]*>(?:<b>[^<]*</b> )?([^<]+)</a>', cell)]
    assert order == ["Sem hora", "Alvorada", "Sessão 1 · Viagem", "Ceia"]
    assert "<b>06:15</b>" in page

    agenda = page.split('calendar-agenda"')[1]
    assert re.findall(r"<strong>([^<]+)</strong>", agenda)[:4] == ["Sem hora", "Alvorada", "Sessão 1 · Viagem", "Ceia"]
    desc = mestre.get(url + "&ordem=desc").get_data(as_text=True).split('calendar-agenda"')[1]
    assert re.findall(r"<strong>([^<]+)</strong>", desc)[:4] == ["Ceia", "Sessão 1 · Viagem", "Alvorada", "Sem hora"]


def test_hoje_no_mundo_com_hora(campanha, mesa, app):
    mestre = mesa.user("mestre")
    url = "/campanhas/%d/calendario" % campanha
    mestre.post(url, data={"action": "set", "day": "1", "month": "1", "year": "1492", "time": "21:00"})
    mestre.post(url, data={"action": "advance", "hours": "8"})
    page = mestre.get(url).get_data(as_text=True)
    assert "2 de Janeiro de 1492 DR, 05:00" in page
    assert "2 de Janeiro de 1492 DR, 05:00" in mestre.get("/campanhas/%d" % campanha).get_data(as_text=True)
    bad = mestre.post(url, data={"action": "set", "day": "1", "month": "1", "year": "1492", "time": "30:00"},
                      follow_redirects=True)
    assert "Hora inválida" in bad.get_data(as_text=True)


def test_exportar_e_importar_mantem_a_hora(campanha, mesa, app):
    import io
    mestre = mesa.user("mestre")
    registrar(mestre, campanha, "Ceia", 3, "20:00")
    exported = mestre.get("/campanhas/%d/exportar" % campanha)
    data = exported.data
    exported.close()
    mesa.user("outro").post("/campanhas/importar", data={"file": (io.BytesIO(data), "c.zip")},
                            content_type="multipart/form-data")
    with app.app_context():
        minutes = sorted(e.world_minute for e in TimelineEntry.query.all())
        assert minutes == [1200, 1200]
