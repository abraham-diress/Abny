"""The Deep Agent wiring (deepagents graph, subagents, tools, stream -> events) with a scripted fake LLM."""

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from agent.agent import run_agent
from agent.brief import parse_brief_rules
from agent.context import RunContext
from shared.conventions import AGENT_SHORTLIST


class ScriptedLLM(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kw):
        return self


def _call(name, args, i):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c{i}", "type": "tool_call"}])


def test_deep_agent_stream_to_events(monkeypatch):
    monkeypatch.setattr("agent.llm.llm_available", lambda: False)
    script = [
        _call("write_todos", {"todos": [{"content": "Scout", "status": "in_progress"},
                                        {"content": "Publish", "status": "pending"}]}, 1),
        _call("task", {"subagent_type": "scout", "description": "Find and rank spaces"}, 2),
        _call("search_spaces", {}, 3),                       # inside scout
        _call("rank_neighborhoods", {"top_n": 5}, 4),        # inside scout
        AIMessage(content="Shortlisted 5 spaces."),          # scout's final answer
        _call("pick_fitout_spaces", {"top_n": 3}, 5),
        _call("task", {"subagent_type": "designer", "description": "Layouts for the top 3"}, 6),
        _call("design_layouts", {"space_ids": ["sample-hou-01", "sample-hou-02", "sample-hou-07"]}, 7),
        AIMessage(content="All valid."),
        _call("publish_results", {"space_ids": ["sample-hou-01", "sample-hou-02", "sample-hou-07"],
                                  "reasons": {"sample-hou-01": "Best storefront"}}, 8),
        AIMessage(content="Done: 3 spaces published."),
    ]
    events = []
    ctx = RunContext(brief=parse_brief_rules("bakery in Houston, 20 seats, under $6k"), sink=events.append)
    run_agent(ctx, model=ScriptedLLM(responses=script))

    types = [e.type for e in events]
    started = [e.agent for e in events if e.type == "subagent_started"]
    finished = [e.agent for e in events if e.type == "subagent_finished"]
    assert started == ["scout", "designer"] and finished == ["scout", "designer"]
    assert "plan_update" in types and AGENT_SHORTLIST in ctx.fs
    assert any(e.type == "tool_call" and e.agent == "scout" for e in events)
    assert len(ctx.results) == 3 and ctx.results[0].layout is not None
    assert "Best storefront" in next(r for r in ctx.results if r.space.space_id == "sample-hou-01").rank_reasons
    assert any(e.type == "log" and "Done" in (e.message or "") for e in events)
