# Teacher

O **Teacher** é um amigo que te ensina inglês conversando, feito com Claude.

Ele não dá aula: bate papo com você sobre o seu dia, trabalho, séries, planos, e o inglês vai
entrando na conversa. Fala principalmente em inglês no seu nível e usa português quando precisa
explicar. Corrige de leve no meio do papo, solta expressões e gírias úteis, lança mini desafios e
traz de volta palavras e erros antigos para você fixar. Quanto mais você evolui, mais inglês ele usa.

Ele lembra de você: seu nível, seus objetivos, as coisas que você contou ("como foi a entrevista?"),
as palavras novas e os erros que se repetem.

Dá para usar de três jeitos:

- **No WhatsApp** (`whatsapp_bot.py`): o Teacher conversa com você no WhatsApp e puxa papo sozinho
  ao longo do dia.
- **No terminal** (`teacher.py`).
- **Dentro do Claude Code** (subagente `english-teacher`).

## WhatsApp

O Teacher conversa com você pela API oficial do WhatsApp (Meta Cloud API). Ele:

- responde cada mensagem que você manda, lembrando da conversa e de tudo que sabe sobre você;
- **puxa conversa sozinho nos horários que você escolher** (padrão: 09:00, 12:30 e 19:30) — mas
  sem ser chato: não interrompe se vocês já estão conversando e não manda outra mensagem se você
  ainda não respondeu a anterior;
- só conversa com o(s) número(s) que você autorizar.

### 1. Crie o app na Meta (uma vez)

1. Entre em <https://developers.facebook.com/apps>, crie um app do tipo **Business** e adicione o
   produto **WhatsApp**.
2. Em **WhatsApp → API Setup** você recebe um número de teste. Anote o **Phone number ID** e gere um
   **token de acesso**. O token temporário expira em 24 h; para uso contínuo crie um *System User*
   no Business Manager e gere um token permanente com a permissão `whatsapp_business_messaging`.
3. Ainda em API Setup, adicione **o seu número de WhatsApp** na lista de destinatários e confirme o
   código que chega no celular.
4. Em **App settings → Basic**, copie o **App secret** (serve para validar que as mensagens vêm da Meta).

### 2. Configure as variáveis de ambiente

| Variável                   | Exemplo              | Descrição                                                           |
|----------------------------|----------------------|---------------------------------------------------------------------|
| `ANTHROPIC_API_KEY`        | `sk-ant-...`         | Sua chave da API do Claude                                          |
| `WHATSAPP_TOKEN`           | `EAAG...`            | Token de acesso da Meta                                             |
| `WHATSAPP_PHONE_NUMBER_ID` | `1234567890`         | Phone number ID do número do bot                                    |
| `WHATSAPP_VERIFY_TOKEN`    | `uma-senha-qualquer` | Senha que você inventa e repete no painel da Meta (passo 3)         |
| `WHATSAPP_APP_SECRET`      | `abc123...`          | App secret (valida a assinatura das mensagens)                      |
| `STUDENT_PHONE`            | `5511999999999`      | Seu número, com DDI e DDD, só dígitos. Vários: separe por vírgula   |
| `CHECKIN_TIMES`            | `09:00,12:30,19:30`  | Horários em que o Teacher puxa conversa (vazio desativa)             |
| `QUIET_MINUTES`            | `120`                | Não puxa conversa se você escreveu nesse intervalo (minutos)        |
| `TIMEZONE`                 | `America/Sao_Paulo`  | Fuso horário dos horários acima                                     |
| `WHATSAPP_TEMPLATE`        | `hello_world`        | Template usado quando a janela de 24 h está fechada (veja abaixo)   |
| `WHATSAPP_TEMPLATE_LANG`   | `en_US`              | Idioma do template                                                  |
| `GRAPH_API_VERSION`        | `v23.0`              | Versão da Graph API da Meta                                         |
| `DATA_DIR`                 | `data`               | Onde ficam conversa e progresso de cada aluno                       |
| `PORT`                     | `8000`               | Porta do servidor                                                   |

### 3. Suba o servidor e conecte o webhook

```bash
pip install -r requirements.txt
python whatsapp_bot.py
```

O servidor precisa de um endereço **HTTPS público** e precisa ficar ligado (é ele que puxa
conversa sozinho). Opções:

- **Para testar no seu computador:** `cloudflared tunnel --url http://localhost:8000` ou
  `ngrok http 8000` dão uma URL pública temporária.
- **Para deixar rodando (recomendado): Render.** O projeto já traz um `render.yaml`. Em
  <https://dashboard.render.com> clique em **New → Blueprint**, escolha este repositório e a branch,
  preencha as chaves que ele pedir e confirme. Ele cria o servidor com um disco para guardar a
  memória do Teacher. Use o plano pago mais barato: no gratuito o servidor dorme quando fica parado,
  e aí o Teacher não consegue puxar conversa. O endereço público aparece no topo da página do serviço
  (algo como `https://teacher-english.onrender.com`).
- Também funciona em Railway, Fly.io ou uma VPS, com disco persistente para a pasta `data/` e o
  comando de início `python whatsapp_bot.py`.

No painel da Meta, em **WhatsApp → Configuration → Webhook**, coloque a URL
`https://SEU-ENDERECO/webhook` e o mesmo `WHATSAPP_VERIFY_TOKEN`, clique em **Verify and save** e
assine o campo **messages**.

Pronto: mande um "Hi!" para o número do bot e o Teacher se apresenta.

### Sobre a regra das 24 horas do WhatsApp

O WhatsApp só deixa uma empresa mandar mensagem livre até 24 h depois da última mensagem da pessoa.
Se vocês ficarem mais de 24 h sem conversar, no próximo horário o Teacher manda um **template**
aprovado pela Meta (uma vez só) e retoma o papo assim que você responder. O `hello_world` já vem
pronto no número de teste, mas é genérico. Para ficar com cara de amigo, crie um template em
**WhatsApp Manager → Message templates** (ex.: nome `saudade`, idioma `pt_BR`, texto
*"E aí, sumido! 😄 Bora trocar uma ideia em inglês hoje?"*) e configure
`WHATSAPP_TEMPLATE=saudade` e `WHATSAPP_TEMPLATE_LANG=pt_BR`.

Por enquanto o Teacher lê só mensagens de texto; se você mandar áudio ou imagem, ele pede para você
escrever.

## Terminal

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # ou: ant auth login
python teacher.py
```

Digite `/sair` para encerrar.

### Configuração opcional

| Variável                | Padrão          | Descrição                                        |
|-------------------------|-----------------|--------------------------------------------------|
| `TEACHER_MODEL`         | `claude-opus-5` | Modelo usado                                     |
| `TEACHER_EFFORT`        | `medium`        | Esforço de raciocínio (`low` … `max`)            |
| `TEACHER_PROGRESS_FILE` | `progress.json` | Onde o progresso é salvo                         |

## Usando dentro do Claude Code

O projeto também traz um subagente em `.claude/agents/english-teacher.md`. Abra o Claude Code
nesta pasta e peça, por exemplo: *"quero bater papo em inglês com o english-teacher"*. Ele usa o mesmo
`progress.json` para lembrar do seu progresso.
