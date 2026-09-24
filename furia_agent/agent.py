"""Loop do agente: Claude + ferramentas do Instagram + busca na web."""

from __future__ import annotations

import os
from typing import Any, Callable

import anthropic

from .prompts import SYSTEM_PROMPT
from .tools import Store, build_tools

DEFAULT_MODEL = "claude-opus-5"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}


class ContentAgent:
    def __init__(
        self,
        store: Store,
        model: str | None = None,
        client: anthropic.Anthropic | None = None,
        web_search: bool = True,
        on_event: Callable[[str], None] | None = None,
    ) -> None:
        self.client = client or anthropic.Anthropic()
        self.model = model or os.getenv("FURIA_AGENT_MODEL", DEFAULT_MODEL)
        self.tools: list[Any] = build_tools(store)
        if web_search:
            self.tools.append(WEB_SEARCH_TOOL)
        self.messages: list[dict[str, Any]] = []
        self.on_event = on_event or (lambda _msg: None)

    def ask(self, user_input: str) -> str:
        """Envia uma mensagem, roda as ferramentas necessárias e devolve a resposta final."""
        self.messages.append({"role": "user", "content": user_input})
        runner = self.client.beta.messages.tool_runner(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=self.tools,
            messages=list(self.messages),
            thinking={"type": "adaptive"},
            cache_control={"type": "ephemeral"},
            # Se o modelo recusar, a API reexecuta no modelo de fallback recomendado.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            max_iterations=25,
        )

        last = None
        for message in runner:
            last = message
            # Espelha o histórico para as próximas perguntas da conversa.
            self.messages.append({"role": "assistant", "content": message.to_param()["content"]})
            for block in message.content:
                if block.type == "tool_use":
                    self.on_event(f"🔧 {block.name}({_short(block.input)})")
                elif block.type == "server_tool_use":
                    self.on_event(f"🌐 {block.name}: {_short(block.input)}")
            if message.stop_reason == "tool_use":
                tool_response = runner.generate_tool_call_response()  # resultado em cache; roda uma vez só
                if tool_response is not None:
                    self.messages.append(tool_response)

        if last is None:
            return ""
        if last.stop_reason == "refusal":
            return "O modelo não pôde responder a esse pedido. Tente reformular."
        text = "\n".join(b.text for b in last.content if b.type == "text").strip()
        if last.stop_reason == "max_tokens":
            text += "\n\n[resposta cortada por limite de tamanho — peça para continuar]"
        return text

    def reset(self) -> None:
        self.messages.clear()


def _short(value: Any, n: int = 80) -> str:
    s = str(value)
    return s if len(s) <= n else s[: n - 1] + "…"
