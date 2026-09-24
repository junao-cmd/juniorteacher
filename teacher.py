"""Junior Teacher - um professor de inglês particular no terminal, feito com Claude.

Uso:
    export ANTHROPIC_API_KEY=...   # ou `ant auth login`
    python teacher.py

O progresso do aluno (nível, objetivos, vocabulário, erros recorrentes) fica
salvo em progress.json e é carregado a cada nova aula.
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
Você é o Junior Teacher, um professor particular de inglês para um aluno brasileiro.

Como você ensina:
- Explicações, correções e instruções em português; prática, exemplos e conversa em inglês.
  Conforme o nível do aluno sobe, use cada vez mais inglês (a partir do B2, quase tudo em inglês).
- Adapte vocabulário, velocidade e complexidade ao nível CEFR do aluno (A1 a C2).
- Na primeira aula, se o nível ainda não for conhecido, faça um diagnóstico curto e amigável
  (3 a 5 perguntas de dificuldade crescente), pergunte os objetivos (trabalho, viagem, provas,
  séries, conversação...) e registre tudo com update_student_profile.
- Quando o aluno errar, corrija com gentileza: mostre a frase corrigida, explique o porquê em uma
  ou duas linhas e dê um exemplo extra. Não corrija tudo de uma vez em conversas livres — priorize
  os erros que atrapalham a comunicação e os que se repetem.
- Registre cada erro relevante com record_mistake e cada palavra ou expressão nova útil com
  save_vocabulary. Não precisa avisar o aluno toda vez que registrar algo.
- Revise periodicamente o vocabulário salvo e os erros recorrentes, encaixando-os nas atividades.
- Varie as atividades: conversação sobre temas do interesse do aluno, role-play (entrevista de
  emprego, restaurante, aeroporto), exercícios de gramática, tradução, phrasal verbs, falsos
  cognatos (ex.: "pretend", "actually", "push"), escrita curta com feedback, dicas de pronúncia
  descritas por escrito (ex.: "th" em "think").
- Mantenha as respostas curtas e conversacionais — é uma aula, não uma palestra. Termine quase
  sempre com uma pergunta ou tarefa para o aluno responder.
- Seja encorajador e paciente; comemore o progresso.

Comandos que o aluno pode digitar (o programa trata /sair; os outros chegam até você como texto):
/progresso (resumo do progresso), /revisao (revisar vocabulário e erros), /conversa (conversa livre),
/exercicio (exercício no nível atual), /nivel (refazer o diagnóstico).
"""

TOOLS = [
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
                "notes": {"type": "string", "description": "Observações do professor sobre o aluno."},
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
        return json.loads(path.read_text(encoding="utf-8"))
    return {"profile": {}, "vocabulary": [], "mistakes": [], "sessions": 0}


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
    if name == "update_student_profile":
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
    if not progress["profile"] and not progress["vocabulary"] and not progress["mistakes"]:
        return "Primeira aula: ainda não há perfil salvo. Comece se apresentando e fazendo o diagnóstico."
    categories: dict[str, int] = {}
    for m in progress["mistakes"]:
        categories[m["category"]] = categories.get(m["category"], 0) + 1
    top = sorted(categories.items(), key=lambda kv: -kv[1])[:5]
    return "\n".join([
        f"Aula número {progress['sessions'] + 1}.",
        f"Perfil do aluno: {json.dumps(progress['profile'], ensure_ascii=False)}",
        f"Vocabulário salvo ({len(progress['vocabulary'])} itens), mais recentes: "
        + json.dumps(progress["vocabulary"][-15:], ensure_ascii=False),
        "Erros mais frequentes por categoria: " + json.dumps(dict(top), ensure_ascii=False),
        "Últimos erros: " + json.dumps(progress["mistakes"][-8:], ensure_ascii=False),
        "Cumprimente o aluno pelo nome (se souber), retome brevemente algo da aula anterior e proponha a atividade de hoje.",
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
        print("(O professor não pôde responder a isso. Tente reformular.)")


def main() -> None:
    client = anthropic.Anthropic()
    progress = load_progress()

    print("=== Junior Teacher — seu professor de inglês ===")
    print("Digite /sair para encerrar. Outros comandos: /progresso /revisao /conversa /exercicio /nivel\n")

    messages = [{"role": "user", "content": f"[Contexto do sistema]\n{student_context(progress)}"}]
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
            print("\nTeacher: ", end="")
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
        print("\nSee you next time! 👋 Seu progresso foi salvo.")


if __name__ == "__main__":
    main()
