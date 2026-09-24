# juniorteacher — Agente de conteúdo do Instagram da FURIA 🐆

Um agente de linha de comando que **lê os dados reais do Instagram da FURIA** (posts, métricas, insights e comentários), **calcula o que está funcionando** e usa o Claude para **criar conteúdo**: ideias de Reels, roteiros, legendas, hashtags e calendários editoriais — sempre justificando com os números do perfil.

## O que ele faz

| Ferramenta do agente | Para quê |
|---|---|
| `get_profile` | Seguidores, bio, total de posts |
| `get_performance_report` | Engajamento por formato, dia da semana, horário (Brasília), tamanho de legenda, hashtags; melhores e piores posts |
| `list_posts` | Posts filtrados/ordenados, usados para aprender a voz da marca |
| `get_post_comments` | O que a torcida está pedindo/sentindo |
| `web_search` | Contexto atual: campeonatos, resultados, trends |
| `save_content` | Salva planos e calendários em `output/*.md` |

As métricas são calculadas em Python (`furia_agent/analytics.py`), sem depender do modelo; o Claude interpreta e cria.

## Instalação

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # preencha as chaves
```

## Testar agora (sem Instagram)

```bash
python -m furia_agent --sample
```

`data/sample_posts.json` tem **dados fictícios** só para testar o fluxo. Só precisa do `ANTHROPIC_API_KEY`.

## Conectar o Instagram da FURIA

O Instagram só libera métricas pela **Instagram Graph API**, que exige:

1. Conta do Instagram **Business ou Creator** ligada a uma **Página do Facebook**.
2. Um app em [developers.facebook.com](https://developers.facebook.com) com as permissões
   `instagram_basic`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement`.
3. Um **token de acesso de longa duração** (Graph API Explorer → gerar token → trocar por um de longa duração).
4. O **ID da conta do Instagram** (não é o @). Para descobrir:
   ```bash
   curl "https://graph.facebook.com/v23.0/me/accounts?fields=name,instagram_business_account&access_token=SEU_TOKEN"
   ```
   O valor em `instagram_business_account.id` vai em `INSTAGRAM_USER_ID`.

Depois:

```bash
python -m furia_agent            # usa o cache em data/cache/ se existir
python -m furia_agent --refresh  # busca tudo de novo (últimos 100 posts + insights)
```

Também dá para carregar um JSON próprio: `python -m furia_agent --json meus_posts.json` (mesmo formato de `data/sample_posts.json`).

## Exemplos de uso

```
você › faça um diagnóstico do perfil nos últimos 90 dias
você › quais formatos e horários performam melhor? mostre os números
você › crie 5 ideias de Reels para a semana do próximo Major de CS2
você › escreva 3 versões de legenda para o anúncio de um novo jogador
você › o que a torcida está pedindo nos comentários dos últimos posts?
você › monte um calendário de 2 semanas misturando CS2, Valorant e loja, e salve
```

Pergunta única, sem modo interativo:

```bash
python -m furia_agent -p "ideias de carrossel para a collab nova da loja"
```

Opções: `--model` (padrão `claude-opus-5`, ou `FURIA_AGENT_MODEL`), `--no-web`, `--limit N`.

## Estrutura

```
furia_agent/
  instagram.py   # Graph API + leitura de JSON
  analytics.py   # métricas de engajamento
  tools.py       # ferramentas expostas ao Claude
  prompts.py     # instruções do estrategista (ajuste a voz/objetivos aqui)
  agent.py       # loop do agente (tool runner do SDK da Anthropic)
  cli.py         # interface de linha de comando
tests/           # pytest
```

## Testes

```bash
pip install pytest && python -m pytest -q
```
