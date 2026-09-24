"""Linha de comando: python -m furia_agent"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from .agent import ContentAgent
from .instagram import GraphAPISource, InstagramError, JSONSource, save_cache
from .tools import Store

CACHE_PATH = Path("data/cache/instagram.json")
SAMPLE_PATH = Path("data/sample_posts.json")

BANNER = """\
🐆 Agente de conteúdo FURIA — Instagram
Exemplos:
  • faça um diagnóstico do perfil nos últimos 90 dias
  • quais formatos e horários performam melhor?
  • crie 5 ideias de Reels para a semana do próximo campeonato de CS2
  • monte um calendário de 2 semanas e salve
Comandos: /nova (limpa a conversa), /sair
"""


def load_store(args: argparse.Namespace) -> Store:
    if args.sample:
        source = JSONSource(SAMPLE_PATH)
        return Store(source, source.load())
    if args.json:
        source = JSONSource(Path(args.json))
        return Store(source, source.load())

    token = os.getenv("INSTAGRAM_ACCESS_TOKEN")
    user_id = os.getenv("INSTAGRAM_USER_ID")
    if not token or not user_id:
        sys.exit(
            "Defina INSTAGRAM_ACCESS_TOKEN e INSTAGRAM_USER_ID no .env "
            "(ou use --sample / --json arquivo.json). Veja o README."
        )
    api = GraphAPISource(token, user_id, os.getenv("INSTAGRAM_GRAPH_VERSION", "v23.0"))

    if CACHE_PATH.exists() and not args.refresh:
        print(f"Usando cache {CACHE_PATH} (use --refresh para buscar de novo).")
        return Store(api, JSONSource(CACHE_PATH).load())

    print(f"Buscando os últimos {args.limit} posts e insights no Instagram…")
    try:
        data = api.load(limit=args.limit)
    except InstagramError as exc:
        sys.exit(f"Falha ao acessar a Graph API: {exc}")
    save_cache(data, CACHE_PATH)
    print(f"{len(data['posts'])} posts de @{data['profile'].get('username')} salvos em {CACHE_PATH}.")
    return Store(api, data)


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Agente que analisa o Instagram da FURIA e cria conteúdo.")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--sample", action="store_true", help="usa dados de exemplo (fictícios) para testar")
    src.add_argument("--json", metavar="ARQUIVO", help="carrega posts de um arquivo JSON")
    parser.add_argument("--refresh", action="store_true", help="ignora o cache e busca na Graph API")
    parser.add_argument("--limit", type=int, default=100, help="quantos posts buscar (padrão 100)")
    parser.add_argument("--model", help="modelo do Claude (padrão: FURIA_AGENT_MODEL ou claude-opus-5)")
    parser.add_argument("--no-web", action="store_true", help="desliga a busca na web")
    parser.add_argument("-p", "--prompt", help="faz uma única pergunta e sai")
    args = parser.parse_args(argv)

    store = load_store(args)
    agent = ContentAgent(store, model=args.model, web_search=not args.no_web, on_event=print)

    def run(question: str) -> None:
        try:
            print("\n" + agent.ask(question) + "\n")
        except anthropic.APIError as exc:
            print(f"\n[erro na API do Claude] {exc}\n")

    if args.prompt:
        run(args.prompt)
        return

    print(BANNER)
    while True:
        try:
            question = input("você › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question in {"/sair", "/exit", "sair"}:
            break
        if question == "/nova":
            agent.reset()
            print("Conversa reiniciada.\n")
            continue
        run(question)


if __name__ == "__main__":
    main()
