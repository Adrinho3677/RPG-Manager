# -*- coding: utf-8 -*-
"""Atualização segura de colunas JSON que várias pessoas mexem ao mesmo tempo.

Mapa tático e tesouro do grupo são JSONs que mestre e jogadores alteram juntos.
Ler, alterar e gravar o JSON inteiro faria um apagar a mudança do outro. Aqui a
gravação só vale se a coluna ainda for o que foi lido (compare-and-swap); se
alguém gravou no meio, lê de novo e reaplica a mudança por cima.
"""
import json

from sqlalchemy import text

from app.extensions import db

ATTEMPTS = 5


class ConflictError(RuntimeError):
    pass


def update_json(table, column, row_id, change, normalize=lambda value: value, obj=None):
    """Aplica `change(valor_normalizado)` e grava. Devolve o valor gravado.

    `change` pode levantar exceção para desistir (nada é gravado). `table` e
    `column` vêm do código, nunca do usuário.
    """
    select = text("SELECT %s FROM %s WHERE id = :id" % (column, table))
    for _ in range(ATTEMPTS):
        raw = db.session.execute(select, {"id": row_id}).scalar()
        try:
            loaded = json.loads(raw) if raw else None
        except ValueError:
            loaded = None
        value = change(normalize(loaded))
        new_raw = json.dumps(value, ensure_ascii=False)
        if raw is None:
            sql = "UPDATE %s SET %s = :new WHERE id = :id AND %s IS NULL" % (table, column, column)
        else:
            sql = "UPDATE %s SET %s = :new WHERE id = :id AND %s = :old" % (table, column, column)
        result = db.session.execute(text(sql), {"new": new_raw, "old": raw, "id": row_id})
        if result.rowcount == 1:
            db.session.commit()
            if obj is not None:
                db.session.expire(obj, [column])
            return value
        db.session.rollback()
    raise ConflictError("Várias pessoas estão mexendo nisso agora. Tente de novo.")
