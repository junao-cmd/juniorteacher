"""Junior - um amigo que te ensina inglês conversando, no terminal, feito com Claude.

Uso:
    export ANTHROPIC_API_KEY=...   # ou `ant auth login`
    python teacher.py

O que ele sabe sobre você (nível, objetivos, coisas que você contou, vocabulário,
erros recorrentes) fica salvo em progress.json e é carregado a cada conversa.
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

import anthropic

MODEL = os.environ.get("TEACHER_MODEL", "claude-opus-5")
EFFORT = os.environ.get("TEACHER_EFFORT", "medium")
PROGRESS_FILE = Path(os.environ.get("TEACHER_PROGRESS_FILE", Path(__file__).with_name("progress.json")))

SYSTEM_PROMPT = """\
Você é o Junior, um amigo brasileiro que fala inglês fluente e está ajudando um amigo a aprender.
Você não é um professor dando aula: é um amigo de verdade batendo papo, e o inglês vai sendo
aprendido no meio da conversa.

Seu jeito:
- Informal, caloroso e bem-humorado, como amigo no WhatsApp: "e aí", "bora", "haha", gírias leves.
  Nada de tom de escola, de "muito bem, aluno" ou de listas de exercícios.
- Seja curioso sobre a vida do seu amigo: dia a dia, trabalho, planos, séries, música, jogos,
  viagens. Faça perguntas, conte coisas, dê opinião, reaja ao que ele conta.
- Lembre das coisas que ele te conta e retome depois ("e aí, como foi a entrevista?"). Guarde tudo
  que for pessoal e importante com remember.
- Mantenha a conversa viva: responda curto, como numa troca de mensagens, e termine quase sempre
  com uma pergunta ou um gancho para ele responder.

Como você ensina sem parecer aula:
- Converse principalmente em inglês, no nível dele, e use português quando precisar explicar algo
  ou quando ele travar. Quanto mais ele evolui, mais inglês (a partir do B2, quase só inglês).
  Adapte vocabulário e complexidade ao nível CEFR dele (A1 a C2).
- Incentive ele a responder em inglês; se responder em português, entre no assunto e mostre de
  leve como diria aquilo em inglês ("em inglês ficaria: ...").
- Correções de amigo: rápidas e sem cerimônia, no meio da resposta ("ah, só uma coisinha: é
  *I've been* e não *I have been since*... enfim, continua!"). Não corrija tudo — foque nos erros
  que atrapalham e nos que se repetem.
- Solte palavras, expressões, gírias e phrasal verbs úteis quando encaixarem no assunto, e às vezes
  um desafio rápido ("como você diria isso em inglês?"), um falso cognato ("cuidado: *pretend* não é
  pretender!") ou uma dica de pronúncia.
- De vez em quando, puxe de volta palavras e erros antigos na conversa para ele fixar.
- Registre sem avisar: erros relevantes com record_mistake, palavras novas com save_vocabulary, e
  nível, objetivos e interesses com update_student_profile.
- No começo da amizade, se ainda não souber o nível dele, descubra conversando (não faça prova):
  comece misturando inglês simples e português e vá subindo conforme ele responde. Pergunte também
  por que ele quer aprender inglês.
- Comemore as vitórias dele e seja paciente: errar faz parte.

Se ele pedir, também dá para ser mais direto: explicar gramática, corrigir um texto inteiro, montar
um exercício, fazer um role-play (entrevista, restaurante, aeroporto) ou resumir o progresso dele.
"""

TOOLS = [
    {
        "name": "remember",
        "description": (
            "Guarda algo pessoal que o amigo contou e vale lembrar depois: acontecimentos, planos, "
            "pessoas, gostos, datas importantes (ex.: 'tem entrevista de emprego na terça', "
            "'o cachorro dele se chama Thor')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"fact": {"type": "string", "description": "O que lembrar, em uma frase."}},
            "required": ["fact"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "update_student_profile",
        "description": (
            "Atualiza o perfil do aluno: nível CEFR estimado, objetivos, interesses e observações. "
            "Use após o diagnóstico inicial e sempre que perceber mudança de nível ou novos interesses. "
            "Envie só os campos que mudaram."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome do aluno."},
                "level": {"type": "string", "enum": ["A1", "A2", "B1", "B2", "C1", "C2"]},
                "goals": {"type": "array", "items": {"type": "string"}},
                "interests": {"type": "array", "items": {"type": "string"}},
                "notes": {"type": "string", "description": "Observações sobre o amigo como aluno."},
            },
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "save_vocabulary",
        "description": "Salva uma palavra ou expressão em inglês que o aluno aprendeu, para revisão futura.",
        "input_schema": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Palavra ou expressão em inglês."},
                "meaning": {"type": "string", "description": "Significado em português."},
                "example": {"type": "string", "description": "Frase de exemplo em inglês."},
            },
            "required": ["term", "meaning"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
    {
        "name": "record_mistake",
        "description": "Registra um erro do aluno para acompanhar padrões e revisar depois.",
        "input_schema": {
            "type": "object",
            "properties": {
                "wrong": {"type": "string", "description": "O que o aluno escreveu."},
                "correct": {"type": "string", "description": "A forma correta."},
                "category": {
                    "type": "string",
                    "description": "Tipo do erro, ex.: 'verb tense', 'preposition', 'false cognate', 'word order'.",
                },
                "explanation": {"type": "string", "description": "Explicação curta em português."},
            },
            "required": ["wrong", "correct", "category"],
            "additionalProperties": False,
        },
        "eager_input_streaming": True,
    },
]


def load_progress(path: Path = PROGRESS_FILE) -> dict:
    if path.exists():
        progress = json.loads(path.read_text(encoding="utf-8"))
        progress.setdefault("memories", [])
        return progress
    return {"profile": {}, "vocabulary": [], "mistakes": [], "memories": [], "sessions": 0}


def save_progress(progress: dict, path: Path = PROGRESS_FILE) -> None:
    path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


def validate(tool: dict, args: object) -> str | None:
    """Minimal schema check (eager input streaming skips server-side validation)."""
    if not isinstance(args, dict):
        return "input must be an object"
    schema = tool["input_schema"]
    missing = [k for k in schema.get("required", []) if not args.get(k)]
    if missing:
        return f"missing required fields: {', '.join(missing)}"
    unknown = set(args) - set(schema["properties"])
    if unknown:
        return f"unknown fields: {', '.join(sorted(unknown))}"
    return None


def run_tool(name: str, args: dict, progress: dict, save=save_progress) -> str:
    today = date.today().isoformat()
    if name == "remember":
        progress["memories"].append({"fact": args["fact"], "date": today})
        result = "guardado"
    elif name == "update_student_profile":
        progress["profile"].update(args)
        result = "perfil atualizado"
    elif name == "save_vocabulary":
        existing = {v["term"].lower() for v in progress["vocabulary"]}
        if args["term"].lower() in existing:
            return "termo já estava salvo"
        progress["vocabulary"].append({**args, "added": today})
        result = "vocabulário salvo"
    elif name == "record_mistake":
        progress["mistakes"].append({**args, "date": today})
        result = "erro registrado"
    else:
        raise ValueError(f"unknown tool {name}")
    save(progress)
    return result


def student_context(progress: dict) -> str:
    """Summary of the saved progress, sent at the start of each lesson."""
    if not any(progress[k] for k in ("profile", "vocabulary", "memories", "mistakes")):
        return (
            "Vocês estão se conhecendo agora: ainda não há nada salvo sobre ele. Apresente-se como o "
            "Junior, puxe papo e vá descobrindo o nome, o nível de inglês e por que ele quer aprender."
        )
    categories: dict[str, int] = {}
    for m in progress["mistakes"]:
        categories[m["category"]] = categories.get(m["category"], 0) + 1
    top = sorted(categories.items(), key=lambda kv: -kv[1])[:5]
    return "\n".join([
        f"Hoje é {date.today().isoformat()}.",
        f"Perfil do amigo: {json.dumps(progress['profile'], ensure_ascii=False)}",
        "Coisas que ele te contou (mais recentes por último): "
        + json.dumps(progress["memories"][-25:], ensure_ascii=False),
        f"Vocabulário salvo ({len(progress['vocabulary'])} itens), mais recentes: "
        + json.dumps(progress["vocabulary"][-15:], ensure_ascii=False),
        "Erros mais frequentes por categoria: " + json.dumps(dict(top), ensure_ascii=False),
        "Últimos erros: " + json.dumps(progress["mistakes"][-8:], ensure_ascii=False),
    ])


def print_text(text: str) -> None:
    print(text, end="", flush=True)


def teacher_turn(
    client: anthropic.Anthropic,
    messages: list,
    progress: dict,
    on_text=print_text,
    save=save_progress,
) -> str | None:
    """Run one teacher turn, executing tool calls until the teacher is done talking.

    Returns everything the teacher said this turn, or None if the request was declined.
    """
    tools_by_name = {t["name"]: t for t in TOOLS}
    said = []
    while True:
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={"effort": EFFORT},
                cache_control={"type": "ephemeral"},
                # Server-side fallback: if a request is declined, the API retries it on
                # Anthropic's recommended fallback model within the same call.
                extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
                extra_body={"fallbacks": "default"},
            ) as stream:
                for text in stream.text_stream:
                    on_text(text)
                response = stream.get_final_message()
        except ValueError:
            # A tool input arrived as unparseable JSON; drop the partial turn and ask again.
            messages.append({"role": "user", "content": "(sistema: sua última chamada de ferramenta veio malformada; tente de novo)"})
            continue
        on_text("\n")

        if response.stop_reason == "refusal":
            if isinstance(messages[-1]["content"], str):
                messages.pop()  # drop the student message that was declined
            return None

        messages.append({"role": "assistant", "content": response.content})
        said.extend(b.text for b in response.content if b.type == "text" and b.text.strip())
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            return "\n\n".join(said)

        results = []
        for block in tool_uses:
            tool = tools_by_name.get(block.name)
            error = "unknown tool" if tool is None else validate(tool, block.input)
            if error is None and response.stop_reason == "max_tokens":
                error = "input truncated"
            if error:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": error, "is_error": True})
            else:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": run_tool(block.name, block.input, progress, save)})
        messages.append({"role": "user", "content": results})


def say(client: anthropic.Anthropic, messages: list, progress: dict) -> None:
    if teacher_turn(client, messages, progress) is None:
        print("(O Junior não conseguiu responder a isso. Tenta falar de outro jeito?)")


def main() -> None:
    client = anthropic.Anthropic()
    progress = load_progress()

    print("=== Junior — seu amigo que te ensina inglês ===")
    print("Digite /sair para encerrar.\n")

    opening = "Puxe conversa com seu amigo, como quem manda a primeira mensagem do dia."
    messages = [{"role": "user", "content": f"[Contexto do sistema]\n{student_context(progress)}\n{opening}"}]
    try:
        say(client, messages, progress)
        while True:
            try:
                user_input = input("\nVocê: ").strip()
            except EOFError:
                break
            if not user_input:
                continue
            if user_input.lower() in {"/sair", "/exit", "/quit"}:
                break
            messages.append({"role": "user", "content": user_input})
            print("\nJunior: ", end="")
            say(client, messages, progress)
    except KeyboardInterrupt:
        pass
    except anthropic.AuthenticationError:
        sys.exit("Erro de autenticação: defina ANTHROPIC_API_KEY ou rode `ant auth login`.")
    except anthropic.RateLimitError:
        sys.exit("Limite de requisições atingido. Espere um pouco e tente de novo.")
    except anthropic.APIConnectionError:
        sys.exit("Sem conexão com a API da Anthropic. Verifique sua internet.")
    except anthropic.APIStatusError as e:
        sys.exit(f"Erro da API ({e.status_code}): {e.message}")
    finally:
        progress["sessions"] += 1
        save_progress(progress)
        print("\nSee ya! 👋 Seu progresso foi salvo.")


if __name__ == "__main__":
    main()
