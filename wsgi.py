# -*- coding: utf-8 -*-
"""Ponto de entrada para o PythonAnywhere.

No painel Web do PythonAnywhere, em "WSGI configuration file", use:

    import sys, os
    path = '/home/SEU_USUARIO/RPGManager'
    if path not in sys.path:
        sys.path.insert(0, path)
    os.environ['SECRET_KEY'] = 'sua-chave-secreta-bem-grande'
    from wsgi import application  # noqa
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:  # carrega variáveis de um .env, se existir
    from dotenv import load_dotenv

    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:
    pass

from app import create_app  # noqa: E402

application = create_app()
app = application
