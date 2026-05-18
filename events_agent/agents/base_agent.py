"""
Base agent class. All specialized agents inherit from this.
Wraps the Anthropic client with tool-use loop logic.
"""

import json
import logging
from typing import Any

import anthropic
import config

logger = logging.getLogger(__name__)


class BaseAgent:
    """
    Runs a tool-use loop against Claude until the model issues a final text reply
    or exhausts max_iterations.
    """

    name: str = "base"
    system_prompt: str = ""
    tools: list[dict] = []

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    def run(self, user_message: str, max_iterations: int = 10) -> str:
        messages = [{"role": "user", "content": user_message}]
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            response = self.client.messages.create(
                model=config.CLAUDE_MODEL,
                max_tokens=4096,
                system=self._build_system(),
                tools=self.tools,
                messages=messages,
            )

            # Collect all tool uses and text blocks
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            text_blocks = [b for b in response.content if b.type == "text"]

            if response.stop_reason == "end_turn" or not tool_uses:
                return "\n".join(b.text for b in text_blocks)

            # Append assistant turn
            messages.append({"role": "assistant", "content": response.content})

            # Execute tools and append results
            tool_results = []
            for tu in tool_uses:
                result = self._dispatch_tool(tu.name, tu.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result) if not isinstance(result, str) else result,
                })

            messages.append({"role": "user", "content": tool_results})

        return "Max iterations reached without a final answer."

    def _build_system(self) -> str:
        base = (
            f"You are the {self.name} for {config.COMPANY_NAME}, "
            f"an events company based in {config.TOWN}, {config.STATE}. "
            f"Owner: {config.OWNER_NAME} ({config.OWNER_EMAIL}). "
            "Act professionally, be concise, and always follow through on tasks. "
            "When you use a tool, wait for its result before drawing conclusions."
        )
        if self.system_prompt:
            base += "\n\n" + self.system_prompt
        return base

    def _dispatch_tool(self, tool_name: str, tool_input: dict) -> Any:
        """Override in subclasses to map tool names to Python callables."""
        raise NotImplementedError(f"{self.name} has no tool handler for '{tool_name}'")
