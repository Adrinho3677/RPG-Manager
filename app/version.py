# -*- coding: utf-8 -*-
"""Marca da versão do código que está rodando.

Serve para perceber um problema chato de hospedagem: no PythonAnywhere, um
`git pull` troca na hora os arquivos servidos ao navegador (JS, CSS), mas o
Python só muda depois do **Reload**. Nesse meio-tempo o site fica com tela
nova e servidor velho — e coisas param de salvar sem dizer por quê.

O mesmo número está em static/js/app.js (BUILD). Se os dois diferirem, o
navegador avisa. Um teste falha se esquecerem de subir os dois juntos.
"""
BUILD = "2026-09-22.2"
