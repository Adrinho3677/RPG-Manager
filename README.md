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
- **Histórico e desfazer**: cada leva de alterações guarda como a ficha estava antes —
  inclusive o dano dado pelo combate e o XP da sessão. Um clique desfaz; dá para restaurar
  qualquer ponto das últimas 60 levas, e restaurar também pode ser desfeito.
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
  - **"Próximo turno"** passa a vez (o cabeçalho mostra *Vez de…*); ao voltar ao primeiro da
    ordem, a rodada sobe e as condições descontam.
  - **🎲 Rolar iniciativa** de todos (ou só do grupo, ou só dos inimigos) pela regra do
    sistema — Ordem: [AGI]d20 pegando o maior + Iniciativa; D&D: 1d20 + Des; Cthulhu: ordem de
    DES, sem dado; Vampiro: DES + RAC. Configurável no editor de sistemas. Os números continuam
    editáveis à mão; combatentes sem ficha ficam com o que o mestre digitou. O resultado dos
    PJs vai para o registro da mesa; o dos inimigos, numa rolagem secreta.
- **Mapa tático** em cada combate: a imagem do mapa com grade por cima e as fichas do
  rastreador como peças. Arraste (ou toque na ficha e depois no quadrado — melhor no celular);
  enquanto arrasta, mostra a distância ("5 quadrados (7,5 m)"). Todos veem os movimentos ao
  vivo. O mestre:
  - ajusta a grade à imagem, a escala do quadrado e se jogadores movem as próprias fichas;
  - **esconde fichas** — some para os jogadores no mapa *e* na ordem de iniciativa;
  - pinta a **névoa de guerra** ("Revelar" / "Cobrir"). A névoa é **de verdade**: o servidor
    recorta a imagem e o jogador recebe só uma cópia com o que não foi revelado coberto de
    preto — nem abrindo o arquivo da imagem ele vê o resto. Inimigos e marcadores debaixo dela
    também não chegam ao navegador. O grupo aparece sempre. (Deixe o mapa *escondido* na
    galeria: se ele estiver visível lá, o jogador abre o original pela galeria — a tela avisa.)
  - põe **marcadores** — 🚪 porta, ⚠️ armadilha, 💰 tesouro, 🎯 alvo, 📌 nota —, que começam
    escondidos e ele revela quando quiser;
  - usa a **tela cheia** para mostrar o mapa numa TV na mesa.

  Qualquer um da mesa desenha **áreas de efeito** — ◯ círculo (raio), ◭ cone e ━ linha — no
  tamanho em metros; o mapa mostra na hora **quem é atingido**. Tira a área quem a pôs (ou o
  mestre).
- **Mapas**: galeria de imagens da campanha, que o mestre pode guardar e revelar depois.
- **📣 Mostrar para a mesa**: o mestre clica numa imagem (Mapas) ou anotação e ela **abre na
  tela de todo mundo**, na hora, como um handout. Se era secreta, fica revelada.
- **⏳ Relógios de progresso** ("o ritual se completa em 6 segmentos"): o mestre enche os
  segmentos com um clique e a mesa vê ao vivo, na visão geral e no combate. Podem ser só do
  mestre.
- **💰 Tesouro do grupo**: itens e moedas do grupo, **separados das fichas**. Qualquer um da
  mesa guarda e tira; **dividir** as moedas entre os PJs marcados mostra quanto cada um recebe
  e deixa a sobra no baú; **entregar** um item registra para quem foi. Nada mexe nas moedas
  ou no inventário pessoal — cada um anota a sua parte na própria ficha. Tudo fica num
  registro.
- **📅 Calendário do mundo**: meses e dias da semana do seu mundo (Gregoriano, 12×30 ou
  personalizado), a era ("DR") e o **hoje no mundo**, que o mestre avança (+1 dia, +1
  semana…). Acontecimentos da linha do tempo e sessões ganham data no mundo e aparecem na
  folhinha.
- **Linha do tempo** e **mesa**.
- **Convite por link**: quem abre faz login ou cria a conta e volta direto para confirmar a
  entrada. Gerar um código novo invalida o link antigo.
- **Exportar campanha**: o mestre baixa um ZIP com tudo (fichas, sessões, anotações — inclusive
  as secretas —, combates com o mapa tático, linha do tempo, relógios, tesouro, calendário,
  rolagens e imagens) em JSON legível. Os e-mails da mesa não vão junto.
- **Importar campanha** (no Painel): o ZIP vira uma campanha nova, com quem importou de
  mestre. As fichas dos jogadores ficam com o mestre até cada dono entrar na mesa; aí ele
  **entrega** a ficha na tela *Mesa*. (Entregar sozinho pelo nome de usuário seria perigoso:
  qualquer um cria uma conta chamada "ana".) Não voltam: as pessoas da mesa, presenças e
  rolagens.
- **📺 Tela da TV**: mapa em tela cheia, iniciativa, relógios, últimas rolagens e handouts —
  **exatamente o que os jogadores veem**, mesmo com o mestre logado na TV (nada escondido
  aparece). Botão "📺 TV" no topo de cada campanha.
- **📜 Tabelas aleatórias** do mestre ("Encontros na estrada": `1-3: Lobos`, `4: Bandidos`…):
  um clique rola e o resultado vai para o registro da mesa. Só do mestre (rola em segredo) ou
  abertas para a mesa.
- **🎲 Rolagens mais ricas**: `1d20+1d4+2`, vantagem/desvantagem (`2d20kh1` / `2d20kl1`, ou o
  seletor no painel, que segue a regra de cada sistema), `4d6kh3`, dados que explodem (`3d6!`),
  `d%` e, na ficha, siglas dos atributos (`1d20+FOR`).
- **🤫 Sussurros**: o jogador fala só com o mestre (e o mestre responde a um jogador), no painel
  de rolagens. O jogador também pode rolar "só o mestre vê".
- **⏸ Atrasar o turno**: tira alguém da ordem; "▶ agir agora" o põe de volta na vez atual.
- No mapa: **criaturas grandes** (2×2 a 4×4), **régua de deslocamento** (área verde até onde a
  ficha anda, lida do campo "Deslocamento" da ficha), **setas do teclado** para mover e
  **↶ Desfazer** (Ctrl+Z) — o jogador desfaz os movimentos dele; o mestre, os de qualquer um.
- **📚 Bestiário entre campanhas**: copie NPCs e criaturas de outras campanhas suas do mesmo
  sistema, sem refazer a ficha.
- **⚔️ Combates preparados**: no roteiro da sessão, prepare os combates antes (criaturas, mapa,
  iniciativa); na hora é só abrir.
- **📅 Lembrete de sessão**: o painel mostra "Sessão 5 é amanhã às 19h. Você vai?" com os botões
  de resposta — sem depender de e-mail. Com e-mail configurado, também chega por e-mail, com
  links que confirmam sem entrar no site.
- **🔒 Diário do personagem**: anotação "só eu" — **nem o mestre lê**, nem vai na exportação.
- **Sair de todos os aparelhos** (em Minha conta); trocar a senha já desconecta os outros.
- **⚙️ Administração** (só para o administrador do site): erros recentes com detalhes, usuários
  com "senha temporária" (sem precisar do console), espaço em disco, limpeza de arquivos que
  sobraram e **download do backup** — o ⚙️ do topo acende quando faz mais de 7 dias sem baixar.
- **Esqueci minha senha**: link por e-mail, que vale 1 hora e funciona uma vez só (precisa
  configurar o envio — veja abaixo).

### Tudo ao vivo, numa consulta só
A página pergunta ao servidor a cada 3 segundos, **uma vez só**, por tudo o que mostra —
rolagens, rastreador, mapa, relógios, handout, tesouro, a própria ficha — e o servidor devolve
só o que mudou. Com a aba escondida (outra aba aberta, celular bloqueado), a página para de
perguntar. No plano gratuito do PythonAnywhere, que limita processamento, isso pesa bem menos
que uma consulta por recurso.

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

São quase 260 testes: fórmulas e dados, CSRF, migrações (inclusive de banco antigo), ficha,
edição simultânea, histórico, combate, mapa tático, permissões, anotações secretas e diário,
rolagens, sussurros, convite, limite de login, validação de e-mail, exportação, importação,
upload, administração e manutenção.
Cada teste usa um banco temporário próprio — o seu banco real nunca é tocado.

**Testes no navegador** (`tests/e2e`): o site sobe de verdade numa porta local e um navegador
sem janela clica nas telas, com mestre e jogador ao mesmo tempo — é o que pega bug de
JavaScript. Usam o **Edge** (ou Chrome) já instalado; nada é baixado além do pacote do
Playwright, que vem no `requirements-dev.txt`. Sem navegador, são pulados.

```bash
python -m pytest tests/e2e
```

Para ver o navegador clicando: `E2E_HEADED=1`. Para usar o Chrome: `E2E_BROWSER=chrome`.
Para pular esses (são os mais lentos): `python -m pytest -m "not e2e"`.

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
mkvirtualenv rpgmanager --python=python3.11
```

> Use `python3.11`, não `/usr/bin/python3.11`: em contas com imagem de sistema mais nova o
> caminho fixo cria um virtualenv quebrado (`pip` falha com `No module named
> '_posixsubprocess'`).

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
os.environ['BEHIND_PROXY'] = '1'     # IP real dos visitantes (limite de login)

# Opcional: e-mail para "Esqueci minha senha" (ver "Enviando e-mail" abaixo)
# os.environ['MAIL_SERVER'] = 'smtp.gmail.com'
# os.environ['MAIL_USERNAME'] = 'seuemail@gmail.com'
# os.environ['MAIL_PASSWORD'] = 'senha-de-app-do-gmail'
# os.environ['SITE_URL'] = 'https://SEU_USUARIO.pythonanywhere.com'

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

### 7. Tarefa diária (backup, lembretes e limpeza)
Na aba **Tasks**, crie **uma** tarefa diária — o plano gratuito só permite uma, por isso o
comando faz tudo de uma vez:

```bash
cd /home/SEU_USUARIO/RPG-Manager && /home/SEU_USUARIO/.virtualenvs/rpgmanager/bin/flask manutencao
```

- **Backup** em `instance/backups/`, mantendo os 14 mais recentes (`BACKUP_KEEP`), pela API de
  backup do SQLite (seguro com o site no ar);
- **lembretes de sessão por e-mail** (só se houver e-mail configurado);
- **limpeza** de retratos sem uso, uploads órfãos e cópias velhas da névoa;
- às segundas, **backup por e-mail** para o administrador (só com e-mail, e se couber).

Se você já tinha a tarefa com `flask backup`, troque por `flask manutencao`.

Backup que só existe no mesmo servidor não protege de tudo: **baixe um de vez em quando** em
⚙️ → *Baixar backup* (o ⚙️ do topo acende quando passa de 7 dias).

### Administrador do site
A página ⚙️ (`/admin`) é só do administrador: por padrão, **a primeira conta criada**. Para
escolher, ponha no arquivo WSGI:

```python
os.environ['ADMIN_USERNAMES'] = 'SeuUsuario'
```

(vários, separados por vírgula). Para os outros, a página nem existe (404).

### Atualizando depois de mudar o código

```bash
cd ~/RPG-Manager && git pull
```

```bash
pip install -r requirements.txt
```

E clique em **Reload** na aba Web — **sempre, depois de todo `git pull`**. Sem isso o site
continua rodando o código antigo na memória, mas lê as páginas (templates) novas do disco: a
mistura dá erro 500 justamente nas telas que mudaram.

Para não depender de lembrar do botão, dá para fazer tudo pelo console — editar o arquivo WSGI
faz o PythonAnywhere recarregar o site:

```bash
cd ~/RPG-Manager && git pull && workon rpgmanager && pip install -r requirements.txt && touch /var/www/SEU_USUARIO_pythonanywhere_com_wsgi.py
```

(troque `SEU_USUARIO` pelo seu usuário em minúsculas; o nome exato do arquivo aparece na aba
Web, em "WSGI configuration file".)

**As migrações do banco rodam sozinhas** quando o site sobe; um banco criado antes das
migrações existirem é reconhecido e atualizado sem perder dados.

### Enviando e-mail (recuperar senha)
Com o envio configurado, o login ganha o "Esqueci minha senha" funcionando. O jeito mais
simples é uma conta do Gmail:

1. Na conta Google, ative a **verificação em duas etapas** e crie uma **senha de app**
   (Conta Google → Segurança → Senhas de app).
2. No arquivo WSGI, descomente as linhas `MAIL_*` e `SITE_URL` e preencha. `MAIL_PASSWORD` é a
   senha de app, **não** a senha da conta.
3. **Reload**.

`SITE_URL` é o endereço do site usado no link do e-mail; com ele, ninguém consegue forjar um
link apontando para outro domínio. Contas gratuitas do PythonAnywhere só conseguem enviar
e-mail por alguns servidores liberados — o Gmail costuma estar entre eles; se o envio falhar,
o erro aparece no **Error log** da aba Web.

### Alguém esqueceu a senha (sem e-mail configurado)
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
| `BEHIND_PROXY` | tenta detectar | Lê o IP real atrás de proxy. **Use `1` no PythonAnywhere**: sem isso todos chegam com o IP do proxy e o bloqueio de login travaria o site inteiro. |
| `DATABASE_URL` | SQLite em `instance/` | Outro banco. |
| `AUTO_MIGRATE` | `1` | `0` se rodar vários processos web ao mesmo tempo. |
| `UPLOAD_DIR` | `instance/uploads` | Onde ficam as imagens enviadas. |
| `BACKUP_DIR` / `BACKUP_KEEP` | `instance/backups` / `14` | Pasta e quantidade de backups. |
| `MAIL_SERVER` / `MAIL_PORT` | — / `587` | Servidor de e-mail (587 = STARTTLS, 465 = SSL). Sem ele, a recuperação por e-mail fica desligada. |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | — | Conta que envia (no Gmail, senha de app). |
| `MAIL_FROM` | `MAIL_USERNAME` | Remetente mostrado. |
| `SITE_URL` | endereço da requisição | Endereço público, usado nos links dos e-mails. |
| `ADMIN_USERNAMES` | a primeira conta | Quem acessa a administração (⚙️). |

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
│   ├── initiative.py      iniciativa de cada sistema
│   ├── board.py           mapa tático (fichas, áreas, marcadores, névoa)
│   ├── fogimage.py        recorta a imagem do mapa com a névoa (Pillow)
│   ├── treasure.py        tesouro do grupo
│   ├── worldcal.py        calendário do mundo
│   ├── cas.py             gravação de JSON sem perder mudanças simultâneas
│   ├── export.py          exportar campanha (ZIP)
│   ├── importer.py        importar campanha
│   ├── mail.py            envio de e-mail
│   ├── tables.py          tabelas aleatórias
│   ├── reminders.py       lembretes de sessão (painel e e-mail)
│   ├── maintenance.py     erros, limpeza, backup para baixar, administrador
│   ├── blueprints/        auth, main, systems, campaigns, characters, uploads,
│   │                      table (relógios, handout, tesouro, calendário, tabelas, sussurros),
│   │                      live (consulta única), admin
│   ├── static/js/         app.js (cliente HTTP + consulta única + handout), sheet.js, dice.js,
│   │                      encounter.js, board.js, clocks.js, treasure.js, tv.js, system-editor.js
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

- **Limite de login**: 5 senhas erradas bloqueiam a conta por 15 minutos, e 20 falhas do mesmo
  IP bloqueiam o IP. Fica no banco, então sobrevive a um Reload. Códigos de convite errados
  também contam, para ninguém descobrir campanhas chutando códigos.
- **Sem redirecionamento para fora**: o `?next=` do login só aceita caminhos do próprio site.
- O tempo de resposta do login não revela se um nome de usuário existe.
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
- Conteúdo escrito por usuários é escapado antes de virar HTML — inclusive dentro dos dados
  JSON embutidos na página (um nome de perícia com `</script>` não vira código).
- **Cabeçalhos**: `X-Frame-Options` (nada de abrir o site num iframe alheio), `nosniff`,
  `Referrer-Policy: same-origin` (o código de convite na URL não vaza para links externos) e
  HSTS em HTTPS.
- **SECRET_KEY obrigatória em produção**: com `SECURE_COOKIES=1`, o site se recusa a subir com
  a chave padrão ou uma chave curta.
- **E-mail**: o formato é conferido (`nome@dominio.com`). O cadastro não confirma o e-mail,
  mas a recuperação de senha só manda o link **para o endereço da conta** — quem cadastrou um
  e-mail alheio não recebe nada. O link vale 1 hora, funciona uma vez (trocar a senha o
  invalida), tem limite de pedidos, e a resposta é a mesma exista a conta ou não.
- **Nada de dados dentro de JavaScript**: confirmações ("Excluir a ficha de…?") vêm de
  `data-confirm`, nunca de `onsubmit="confirm('{{ nome }}')"` — ali o nome escolhido por um
  jogador viraria código rodando no navegador do mestre. Um teste falha se isso voltar.
- **Importação**: o ZIP é conferido antes de abrir (quantidade de arquivos, tamanho
  descompactado, taxa de compressão — contra "bomba de zip"); imagens passam pela mesma
  checagem dos uploads; se algo falhar no meio, nada é gravado.
- Fórmulas nunca são executadas como código.

---

## No radar

- **Instalar como app (PWA)**: ícone na tela inicial e tela cheia no celular.
