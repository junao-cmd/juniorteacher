# juniorteacher

Um agente que é seu professor particular de inglês, feito com Claude.

Ele faz um diagnóstico do seu nível (A1–C2) na primeira aula, pergunta seus objetivos e depois
dá aulas no terminal: conversação, role-play, gramática, vocabulário, falsos cognatos e correção
de textos. Explica em português e pratica em inglês, usando mais inglês conforme você evolui.

Tudo o que ele aprende sobre você (nível, objetivos, palavras novas, erros recorrentes) fica em
`progress.json`, e cada aula nova começa de onde a anterior parou.

## Como usar

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
