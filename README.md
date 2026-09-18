# Grimório — gerenciador de campanhas de RPG

Site em Python (Flask) para mesas de RPG: fichas que se adaptam ao sistema jogado,
planejamento de sessões, anotações com segredos, combate ligado às fichas, rolagens
compartilhadas com a mesa, mapas e linha do tempo.

---

## O que ele faz

### Modelos de ficha (sistemas)
Cada campanha usa um **sistema**, que define a estrutura da ficha. Já vêm prontos:

| Sistema | Atributos | Rolagem | Perícias |
|---|---|---|---|
| Ordem Paranormal | 5 (0 a 5) | N d20, pega o maior | graus de treino (+0/+5/+10/+15) |
| D&D 5ª Edição | 6 (com modificador) | 1d20 + mod | proficiência / especialista |
| Tormenta 20 | 6 (já em modificador) | 1d20 + mod | graus de treino (+0/+2/+4/+6) |
| Chamado de Cthulhu | 9 (percentuais) | 1d100 abaixo do valor | valor percentual |
| Vampiro: A Máscara | 9 (pontos 1-5) | parada de d10, sucesso em 6+ | pontos somados ao atributo |
| Genérico | 3 | 1d20 + mod | bônus simples |

Cada um já vem com carga, moedas, regras de descanso e nomes de seção do seu sistema.

> Capacidade de carga e regras de descanso são um ponto de partida razoável, não a
> citação oficial de cada livro. Confira com a regra da sua mesa e ajuste no editor.

Você pode **duplicar qualquer um e editar**, criar do zero, ou **importar** um sistema que
outro mestre **exportou**. No editor dá para:

- adicionar/remover/reordenar **atributos**, **perícias** e **campos de identidade**;
- criar **barras** (vida, mana, sanidade, munição...) com cor, regra de **descanso curto e
  longo** e **máximo calculado por fórmula** — `20 + VIG * 4`, `max(1, NEX / 5)`;
- escolher como os atributos são exibidos, como as perícias funcionam e como o sistema rola;
- configurar a **carga** (peso, espaços ou nada), as **moedas** e os nomes das seções.

#### Fórmulas
Usam siglas ou chaves dos atributos e campos numéricos da ficha, `+ - * /`, parênteses,
`min()` e `max()`. A divisão arredonda para baixo. Em D&D, a sigla vale o modificador.
São avaliadas por um analisador próprio ([app/formula.py](app/formula.py)) — nunca `eval()` —,
então uma fórmula escrita por alguém não executa código.

### Ficha de personagem
Organizada em abas — **Combate, Perícias, Magias (ou Rituais, Disciplinas…), Inventário,
Evolução e Personagem** — para caber no celular durante a sessão.

- **Salvamento automático**: o que você digita é salvo sozinho segundos depois.
- **Edição simultânea segura**: se o mestre mexe no seu PV pelo combate enquanto você edita
  o inventário, as duas mudanças ficam. A ficha avisa quando mudou em outro lugar e bloqueia
  só os botões que poderiam apagar a mudança da outra pessoa (descanso, adicionar campo).
- Barras com atual/máximo/temporário, **descanso curto e longo** conforme a regra do sistema.
- **Inventário com peso e carga**, sobrecarga, dinheiro nas moedas do sistema.
- **Ataques** com teste e dano roláveis, **magias**, **habilidades**, **condições** com duração.
- **Experiência** com log de evolução.
- Retrato por **upload** de imagem ou link.
- Atributos, barras, perícias e campos extras **criados só naquela ficha**.
- **Imprimir / PDF**: página A4 em preto no branco (o navegador gera o PDF).

### Rolagens
Os dados rolam **no servidor**: numa campanha, o que chega na mesa é o que o servidor
sorteou, e ninguém consegue forjar um 20 natural pelo console do navegador. Cada rolagem
entra no **registro da mesa**, que atualiza sozinho na ficha e na tela de combate. O mestre
pode fazer **rolagens secretas**.

### Gerenciamento de campanha
- **Visão geral** com próxima sessão, pistas recém-reveladas e anotações fixadas.
- **Sessões** com data, **horário** e **confirmação de presença** ("vou / talvez / não posso"),
  roteiro secreto, sinopse, resumo, checklist de cenas ao vivo e distribuição de XP para a mesa.
- **Anotações** por categoria, com visibilidade **mesa toda / só o mestre / jogadores
  escolhidos**, e botão para **revelar** um segredo para alguém no meio da sessão.
- **Elenco e bestiário**: NPCs e criaturas; criaturas entram no combate como cópias.
- **Combate**: PJs e NPCs entram **ligados à ficha** — dano no rastreador vai para o PV deles.
  Condições com duração perdem uma rodada por rodada e somem quando acabam. Jogadores
  acompanham ao vivo, mas **não recebem o PV dos inimigos**, só "ileso / ferido / grave".
- **Mapas**: galeria de imagens da campanha, que o mestre pode guardar e revelar depois.
- **Linha do tempo** e **mesa** com código de convite.

---

## Rodando na sua máquina

```bash
pip install -r requirements.txt
```

```bash
python run.py
```

Abra <http://localhost:5000>. O banco SQLite é criado e **migrado sozinho** em
`instance/rpgmanager.db`. Para o servidor recarregar ao salvar um arquivo:

```bash
python run.py --reload
```

Sem a flag roda num processo só: o reloader do Flask cria um processo filho que sobrevive a
quem o iniciou e fica segurando a porta.

### Testes

```bash
pip install -r requirements-dev.txt
```

```bash
python -m pytest
```

São 95 testes: fórmulas e dados, CSRF, migrações (inclusive de banco antigo), ficha,
edição simultânea, combate, permissões, anotações secretas, rolagens, importação e upload.
Cada teste usa um banco temporário próprio — o seu banco real nunca é tocado.

---

## Publicando no PythonAnywhere

### 1. Suba o código
No **Bash console** do PythonAnywhere:

```bash
git clone https://github.com/Adrinho3677/RPG-Manager.git
```

O caminho final deve ficar `/home/SEU_USUARIO/RPG-Manager`.

### 2. Crie o virtualenv e instale as dependências

```bash
mkvirtualenv rpgmanager --python=/usr/bin/python3.11
```

```bash
pip install -r /home/SEU_USUARIO/RPG-Manager/requirements.txt
```

### 3. Crie o web app
Aba **Web → Add a new web app → Manual configuration → Python 3.11**, e aponte:

- **Source code** e **Working directory**: `/home/SEU_USUARIO/RPG-Manager`
- **Virtualenv**: `/home/SEU_USUARIO/.virtualenvs/rpgmanager`

### 4. Configure o WSGI
Clique no link do **WSGI configuration file**, apague tudo e deixe assim:

```python
import os
import sys

path = '/home/SEU_USUARIO/RPG-Manager'
if path not in sys.path:
    sys.path.insert(0, path)

os.environ['SECRET_KEY'] = 'ponha-aqui-uma-chave-longa-e-aleatoria'
os.environ['SECURE_COOKIES'] = '1'   # o PythonAnywhere usa HTTPS
os.environ['TIMEZONE'] = 'America/Sao_Paulo'

from wsgi import application  # noqa
```

Gere a chave com:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

> **Não ative `SECURE_COOKIES` rodando local em `http://localhost`** — o navegador descarta o
> cookie de sessão e o login para de funcionar.

### 5. Arquivos estáticos
Na aba **Web**, em **Static files**:

| URL | Directory |
|---|---|
| `/static/` | `/home/SEU_USUARIO/RPG-Manager/app/static/` |

> **Não mapeie `/arquivos/` nem a pasta `instance/uploads` como estáticos.** As imagens
> enviadas passam pelo Flask de propósito: é ele que confere se quem pede pode ver aquele
> mapa. Servir a pasta direto entregaria mapas secretos a qualquer um com o link.

### 6. Recarregue
Botão verde **Reload**. O site fica em `https://SEU_USUARIO.pythonanywhere.com`.

### 7. Backup diário
Na aba **Tasks**, crie uma tarefa diária (o plano gratuito permite uma):

```bash
cd /home/SEU_USUARIO/RPG-Manager && /home/SEU_USUARIO/.virtualenvs/rpgmanager/bin/flask backup
```

Guarda cópias em `instance/backups/`, mantendo as 14 mais recentes (`BACKUP_KEEP`). A cópia
usa a API de backup do SQLite, segura mesmo com o site no ar. Baixe uma de vez em quando pela
aba **Files** — backup que só existe no mesmo servidor não protege de tudo.

### Atualizando depois de mudar o código

```bash
cd ~/RPG-Manager && git pull
```

```bash
pip install -r requirements.txt
```

E clique em **Reload**. **As migrações do banco rodam sozinhas** quando o site sobe; um banco
criado antes das migrações existirem é reconhecido e atualizado sem perder dados.

### Alguém esqueceu a senha
No **Bash console**:

```bash
workon rpgmanager && cd ~/RPG-Manager && flask redefinir-senha NOME_DO_USUARIO
```

Aparece uma senha temporária. A pessoa entra com ela e troca em **Minha conta** (clicando no
próprio nome, no topo).

### Usando MySQL (opcional)
Para muita gente editando ao mesmo tempo, o MySQL aguenta melhor que o SQLite:

```bash
pip install pymysql cryptography
```

E no arquivo WSGI, antes do `from wsgi import application`:

```python
os.environ['DATABASE_URL'] = (
    'mysql+pymysql://SEU_USUARIO:SENHA@SEU_USUARIO.mysql.pythonanywhere-services.com/SEU_USUARIO$rpg'
)
```

O comando `flask backup` só funciona com SQLite; no MySQL use o backup da aba **Databases**.

### Variáveis de ambiente

| Variável | Padrão | Para quê |
|---|---|---|
| `SECRET_KEY` | — | **Obrigatória em produção.** Assina as sessões. |
| `SECURE_COOKIES` | `0` | `1` em HTTPS: cookie de sessão só trafega criptografado. |
| `TIMEZONE` | `America/Sao_Paulo` | Fuso para mostrar horários (o banco guarda em UTC). |
| `DATABASE_URL` | SQLite em `instance/` | Outro banco. |
| `AUTO_MIGRATE` | `1` | `0` se rodar vários processos web ao mesmo tempo. |
| `UPLOAD_DIR` | `instance/uploads` | Onde ficam as imagens enviadas. |
| `BACKUP_DIR` / `BACKUP_KEEP` | `instance/backups` / `14` | Pasta e quantidade de backups. |

---

## Estrutura

```
RPG-Manager/
├── app/
│   ├── __init__.py        fábrica do app, migração automática, erros
│   ├── models.py          tabelas
│   ├── sheet.py           monta a ficha: sistema + campos extras, carga, descanso, fórmulas
│   ├── formula.py         avaliador seguro de fórmulas
│   ├── dice.py            rolagens no servidor
│   ├── commands.py        flask backup, flask redefinir-senha
│   ├── presets.py         os 6 sistemas prontos
│   ├── blueprints/        auth, main, systems, campaigns, characters, uploads
│   ├── static/js/         app.js (cliente HTTP), sheet.js, dice.js, encounter.js, system-editor.js
│   └── templates/
├── migrations/            histórico do banco (Alembic)
├── tests/                 pytest
├── config.py              configuração por variável de ambiente
├── run.py                 servidor local
└── wsgi.py                entrada do PythonAnywhere
```

### Mudou um modelo? Gere a migração

```bash
flask db migrate -m "o que mudou"
```

Confira o arquivo gerado em `migrations/versions/` e rode os testes: um deles falha se
algum modelo ficou sem migração.

---

## Segurança

- **CSRF**: todo formulário e toda chamada do JavaScript levam token. Outro site não
  consegue fazer um mestre logado apagar a campanha.
- **Cookies** `HttpOnly` e `SameSite=Lax`; `Secure` com `SECURE_COOKIES=1`.
- Senhas com hash (`werkzeug.security`).
- **Segredos não saem do servidor**: anotações só do mestre, roteiros, PV e notas dos inimigos
  e rolagens secretas não são enviados ao navegador de quem não pode ver — nem aparecem no
  DevTools.
- **Uploads**: o tipo é detectado pelos bytes do arquivo (só PNG, JPG, GIF, WEBP; SVG é
  recusado porque pode carregar script), o nome no disco é aleatório, e a resposta vai com
  `nosniff` e CSP restritiva.
- Conteúdo escrito por usuários é escapado antes de virar HTML.
- Fórmulas nunca são executadas como código.
