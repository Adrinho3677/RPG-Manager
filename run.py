"""Servidor de desenvolvimento local.

    python run.py              inicia em http://localhost:5000
    python run.py --reload     idem, recarregando quando o código mudar
    PORT=8000 python run.py    escolhe outra porta

O reloader do Flask roda o servidor num processo filho. Se quem iniciou o
processo pai for encerrado, esse filho continua vivo e segura a porta — por
isso a recarga automática aqui é opcional, e não o padrão.
"""
import os
import sys

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(
        debug=True,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", 5000)),
        use_reloader="--reload" in sys.argv,
    )
