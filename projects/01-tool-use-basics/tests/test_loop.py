"""The loop against a scripted fake client: no API key, no network. Responses are real SDK types."""
import json

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

import loop
import tools


def msg(*content, stop="tool_use"):
    return Message(id="m", type="message", role="assistant", model="fake", stop_reason=stop,
                   content=list(content), usage=Usage(input_tokens=10, output_tokens=5))


def use(id_, name, **args):
    return ToolUseBlock(type="tool_use", id=id_, name=name, input=args)


def text(t):
    return TextBlock(type="text", text=t)


class FakeClient:
    """Returns scripted responses in order and records every request."""
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []
        self.messages = self

    def create(self, **kw):
        self.requests.append(json.loads(json.dumps(kw, default=lambda o: o.model_dump(exclude_none=True))))
        return self.responses.pop(0)


def test_two_tool_rounds_then_answer():
    client = FakeClient(
        msg(text("Let me look."), use("t1", "list_runs", project="payments", limit=2)),
        msg(use("t2", "failed_cases", run_id="r50"), use("t3", "failed_cases", run_id="r47")),   # parallel
        msg(text("r50 failed with a 502 and a refund mismatch."), stop="end_turn"),
    )
    r = loop.run("Why did payments fail?", client)
    assert r.answer == "r50 failed with a 502 and a refund mismatch." and r.stop_reason == "end_turn"
    assert r.steps == 3 and r.tool_calls == ["list_runs", "failed_cases", "failed_cases"]
    assert (r.input_tokens, r.output_tokens) == (30, 15)

    # request 2: history = question, assistant tool_use, user tool_result with the matching id
    second = client.requests[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    [result] = second[2]["content"]
    assert result["tool_use_id"] == "t1" and json.loads(result["content"])[0]["run_id"] == "r50"

    # request 3: BOTH parallel results in ONE user message, in order
    third = client.requests[2]["messages"][-1]["content"]
    assert [b["tool_use_id"] for b in third] == ["t2", "t3"]
    assert "refund amount 150.00 MXN expected" in third[0]["content"]
    assert client.requests[0]["tools"] == tools.TOOLS


def test_tool_error_goes_back_to_the_model():
    client = FakeClient(msg(use("t1", "failed_cases", run_id="r99")),
                        msg(text("No run r99."), stop="end_turn"))
    loop.run("r99?", client)
    [result] = client.requests[1]["messages"][-1]["content"]
    assert result["is_error"] is True and "Unknown run 'r99'" in result["content"]


def test_max_steps_guard():
    client = FakeClient(*[msg(use(f"t{i}", "list_runs", project="search")) for i in range(3)])
    r = loop.run("loop forever", client, max_steps=3)
    assert r.stop_reason == "max_steps" and r.steps == 3


@pytest.mark.parametrize("name,args,error", [
    ("list_runs", {"project": "checkout", "limit": 2}, None),
    ("list_runs", {"project": "billing"}, "Unknown project"),
    ("failed_cases", {"run_id": "r46"}, None),
    ("failed_cases", {}, "missing"),
    ("drop_table", {}, "Unknown tool"),
])
def test_run_tool(name, args, error):
    content, is_error = tools.run_tool(name, args)
    assert is_error == bool(error)
    if error:
        assert error in content
    elif name == "list_runs":
        assert [r["run_id"] for r in json.loads(content)] == ["r48", "r45"]
    else:
        assert json.loads(content) == []                      # r46 was clean


def test_schemas_match_implementations():
    import inspect
    for t in tools.TOOLS:
        params = inspect.signature(tools.IMPLEMENTATIONS[t["name"]]).parameters
        assert set(t["input_schema"]["properties"]) == set(params)
        assert len(t["description"]) > 40                     # the model decides from this text
