"""Thin application adapter around the oag-agent runtime."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Iterator


class OagAgentRuntime:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self._agent = None
        self._error = ""
        self._lock = threading.RLock()
        self._configure()

    def _configure(self) -> None:
        model = (
            os.environ.get("OAG_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("LLM_MODEL")
        )
        base_url = os.environ.get("OPENAI_BASE_URL") or os.environ.get("LLM_API_URL")
        api_key = (
            os.environ.get("OPENAI_API_KEY")
            or os.environ.get("LLM_API_KEY")
            or ("local" if base_url else None)
        )
        disable_reasoning = _is_truthy(os.environ.get("LLM_DISABLE_REASONING"))
        if not model:
            self._error = "未配置 OAG_MODEL、OPENAI_MODEL 或 LLM_MODEL"
            return
        if not api_key:
            self._error = "未配置 OPENAI_API_KEY 或 LLM_API_KEY"
            return
        try:
            from openai import OpenAI

            from oag.agent import Agent
            from oag.harness import Harness
            from oag.ontology.loader import load_domain
            from oag.runtime import HarnessConfig

            ontology, repository, registry = load_domain(self.root / "oms")
            client_args: dict[str, Any] = {"api_key": api_key}
            if base_url:
                client_args["base_url"] = base_url
            client = OpenAI(**client_args)
            harness = Harness(
                ontology=ontology,
                repository=repository,
                registry=registry,
                llm_client=client,
                model=model,
                config=HarnessConfig(
                    enable_write_confirmation=True,
                    enable_analysis_tools=False,
                    max_turns=8,
                    runtime_context={"surface": "OMS Web"},
                    llm_extra_body=(
                        {"chat_template_kwargs": {"enable_thinking": False}}
                        if disable_reasoning
                        else {}
                    ),
                    append_system_prompt="/no_think" if disable_reasoning else "",
                ),
            )
            self._agent = Agent(
                harness,
                client,
                model=model,
                db_dir=str(self.root / ".oag_data"),
            )
        except Exception as exc:  # The web shell remains usable without LLM credentials.
            self._error = f"OAG Agent 初始化失败: {exc}"

    def status(self) -> dict[str, Any]:
        return {
            "available": self._agent is not None,
            "runtime": "oag-agent",
            "message": "已连接" if self._agent is not None else self._error,
        }

    def chat(self, message: str, session_id: str) -> Iterator[dict[str, Any]]:
        if self._agent is None:
            yield {"type": "error", "message": self._error}
            return
        with self._lock:
            yield from self._agent.chat_stream_sse(message, session_id=session_id)

    def confirm(self, session_id: str, approved: bool, answer: str | None = None) -> Iterator[dict[str, Any]]:
        if self._agent is None:
            yield {"type": "error", "message": self._error}
            return
        from oag.runtime.events import event_to_dict

        with self._lock:
            for event in self._agent.confirm_tool(session_id, approved=approved, answer=answer):
                yield event_to_dict(event)


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
