"""
The agent loop, written by hand with the Anthropic Messages API. Every framework in this repo automates
exactly this:

    messages = [user question]
    loop:
        response = model(messages, tools)
        if response.stop_reason != "tool_use":  done -> the text is the answer
        run every tool_use block, append ONE user message with all the tool_result blocks
        (each tool_result.tool_use_id must match its tool_use.id)

    python loop.py "Which checkout tests failed most recently?"
    python loop.py "Why did run r50 fail?" --show-messages     # print every request/response block
"""
import argparse
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from tools import TOOLS, run_tool

MODEL = os.getenv("TRIAGE_MODEL", "claude-sonnet-5-5")
SYSTEM = ("You answer questions about nightly test runs using the tools. Cite run ids. "
          "If a tool returns an error, fix the arguments and try again. Be brief.")


@dataclass
class LoopResult:
    answer: str
    steps: int                                  # model calls
    tool_calls: list[str] = field(default_factory=list)
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


def _blocks(content) -> list[dict]:
    """SDK content blocks -> plain dicts (for printing)."""
    return [b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else b for b in content]


def run(question: str, client, *, model: str = MODEL, max_steps: int = 8, show=None) -> LoopResult:
    """`client` is anthropic.Anthropic() or anything with the same messages.create()."""
    show = show or (lambda role, blocks: None)
    messages = [{"role": "user", "content": question}]
    result = LoopResult(answer="", steps=0)
    show("user", [{"type": "text", "text": question}])

    while result.steps < max_steps:
        response = client.messages.create(model=model, max_tokens=1024, system=SYSTEM, tools=TOOLS,
                                          messages=messages)
        result.steps += 1
        result.input_tokens += response.usage.input_tokens
        result.output_tokens += response.usage.output_tokens
        result.stop_reason = response.stop_reason
        show(f"assistant (stop_reason={response.stop_reason})", _blocks(response.content))

        # 1. keep the assistant turn in the history exactly as returned (tool_use blocks included)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":          # "end_turn", "max_tokens", "refusal", ...
            result.answer = "".join(b.text for b in response.content if b.type == "text")
            return result

        # 2. run EVERY tool_use block (the model may ask for several at once)
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result.tool_calls.append(block.name)
            content, is_error = run_tool(block.name, block.input)
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": content,
                                 **({"is_error": True} if is_error else {})})

        # 3. send all results back in ONE user message, then ask the model again
        messages.append({"role": "user", "content": tool_results})
        show("user (tool results)", tool_results)

    result.answer = f"Stopped after {max_steps} model calls without a final answer."
    result.stop_reason = "max_steps"
    return result


def print_blocks(role: str, blocks: list[dict]) -> None:
    print(f"\n── {role} " + "─" * max(0, 60 - len(role)))
    for b in blocks:
        print(json.dumps(b, indent=2, ensure_ascii=False)[:1500])


def main() -> None:
    import anthropic
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?", default="Which checkout tests failed most recently, and why?")
    ap.add_argument("--show-messages", action="store_true", help="print every block sent and received")
    ap.add_argument("--max-steps", type=int, default=8)
    args = ap.parse_args()
    r = run(args.question, anthropic.Anthropic(), max_steps=args.max_steps,
            show=print_blocks if args.show_messages else None)
    print("\n" + r.answer)
    print(f"\n[{r.steps} model calls · tools: {', '.join(r.tool_calls) or 'none'} · "
          f"{r.input_tokens} in / {r.output_tokens} out tokens · stop_reason={r.stop_reason}]")


if __name__ == "__main__":
    main()
