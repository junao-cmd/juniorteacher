# juniorteacher

Um agente que é seu professor particular de inglês, feito com Claude.

Ele faz um diagnóstico do seu nível (A1–C2) na primeira aula, pergunta seus objetivos e depois
dá aulas no terminal: conversação, role-play, gramática, vocabulário, falsos cognatos e correção
de textos. Explica em português e pratica em inglês, usando mais inglês conforme você evolui.

Tudo o que ele aprende sobre você (nível, objetivos, palavras novas, erros recorrentes) fica em
`progress.json`, e cada aula nova começa de onde a anterior parou.

Dá para usar de três jeitos:

- **No WhatsApp** (`whatsapp_bot.py`): o professor manda a aula do dia no seu WhatsApp e responde
  quando você escreve.
- **No terminal** (`teacher.py`).
- **Dentro do Claude Code** (subagente `english-teacher`).

## WhatsApp

O professor conversa com você pela API oficial do WhatsApp (Meta Cloud API). Ele:

- responde cada mensagem que você manda, lembrando da conversa e do seu progresso;
- **todo dia, no horário que você escolher, manda a aula do dia por conta própria**;
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
| `DAILY_LESSON_TIME`        | `19:00`              | Horário da aula diária (vazio desativa)                             |
| `TIMEZONE`                 | `America/Sao_Paulo`  | Fuso horário da aula diária                                         |
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

O servidor precisa de um endereço **HTTPS público** e precisa ficar ligado (é ele que manda a aula
diária). Opções:

- **Para testar no seu computador:** `cloudflared tunnel --url http://localhost:8000` ou
  `ngrok http 8000` dão uma URL pública temporária.
- **Para deixar rodando:** um serviço como Render, Railway, Fly.io ou uma VPS, com disco persistente
  para a pasta `data/` e o comando de início `python whatsapp_bot.py`.

No painel da Meta, em **WhatsApp → Configuration → Webhook**, coloque a URL
`https://SEU-ENDERECO/webhook` e o mesmo `WHATSAPP_VERIFY_TOKEN`, clique em **Verify and save** e
assine o campo **messages**.

Pronto: mande um "Hi!" para o número do bot e a primeira aula começa.

### Sobre a regra das 24 horas do WhatsApp

O WhatsApp só deixa uma empresa mandar mensagem livre até 24 h depois da última mensagem da pessoa.
Se na hora da aula diária você não tiver falado com o professor nas últimas 24 h, ele manda um
**template** aprovado pela Meta e começa a aula assim que você responder. O `hello_world` já vem
pronto no número de teste, mas é genérico. Para um lembrete de verdade, crie um template em
**WhatsApp Manager → Message templates** (ex.: nome `aula_do_dia`, idioma `pt_BR`, texto
*"Hora da sua aula de inglês! 📚 Responde aqui pra gente começar."*) e configure
`WHATSAPP_TEMPLATE=aula_do_dia` e `WHATSAPP_TEMPLATE_LANG=pt_BR`.

Por enquanto o professor lê só mensagens de texto; áudios e imagens recebem um pedido para escrever.

## Terminal

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...   # ou: ant auth login
python teacher.py
```

Comandos durante a aula:

| Comando      | O que faz                                  |
|--------------|--------------------------------------------|
| `/progresso` | Resumo do seu progresso                    |
| `/revisao`   | Revisão do vocabulário e dos erros salvos  |
| `/conversa`  | Conversa livre                             |
| `/exercicio` | Exercício no seu nível                     |
| `/nivel`     | Refaz o diagnóstico de nível               |
| `/sair`      | Encerra e salva o progresso                |

### Configuração opcional

| Variável                | Padrão          | Descrição                                        |
|-------------------------|-----------------|--------------------------------------------------|
| `TEACHER_MODEL`         | `claude-opus-5` | Modelo usado                                     |
| `TEACHER_EFFORT`        | `medium`        | Esforço de raciocínio (`low` … `max`)            |
| `TEACHER_PROGRESS_FILE` | `progress.json` | Onde o progresso é salvo                         |

## Usando dentro do Claude Code

O projeto também traz um subagente em `.claude/agents/english-teacher.md`. Abra o Claude Code
nesta pasta e peça, por exemplo: *"use o english-teacher para me dar uma aula"*. Ele usa o mesmo
`progress.json` para lembrar do seu progresso.
