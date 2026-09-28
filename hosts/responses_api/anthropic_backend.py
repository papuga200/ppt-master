"""Claude behind the host: one Responses-shaped turn served by the Anthropic Messages API.

The host speaks the OpenAI Responses protocol (instructions, input items, function tools, `output` items). When
PPT_MASTER_API_BASE points at api.anthropic.com, `host._call` hands the payload here instead: the host runs stateless
(it resends its whole history each turn) and this module translates that history into Messages, calls the official
SDK, and returns the reply as Responses items the host already understands.

Claude's own assistant content (thinking blocks included) is carried in the history verbatim as an
`anthropic_assistant` item and sent back unchanged: newer Claude models tie thinking blocks to the conversation, and
the history stays append-only. The `function_call` / `message` items derived from it are marked `_derived` and skipped
when the history is rebuilt.

Caching: the system prompt (the shared ~200k-character page-author brief and documents) carries a cache breakpoint,
and automatic caching adds one at the end of the conversation, so each turn reads the previous turn's prefix.
"""

from __future__ import annotations

import base64
import json
import re

import anthropic

# USD per token, Anthropic list price (Claude API). Cache writes use the 5-minute rate (1.25x input).
PRICES = {"claude-opus-5-5": {"input": 4e-6, "cache_write": 5e-6, "cache_read": 0.2e-6, "output": 20e-6},
          "claude-fable-5-1": {"input": 10e-6, "cache_write": 12.5e-6, "cache_read": 0.25e-6, "output": 50e-6}}
_CLIENTS: dict[str, anthropic.Anthropic] = {}


def _client(key: str) -> anthropic.Anthropic:
    if key not in _CLIENTS:
        _CLIENTS[key] = anthropic.Anthropic(api_key=key, max_retries=4, timeout=1800.0)
    return _CLIENTS[key]


def _tools(tools: list[dict]) -> list[dict]:
    return [{"name": t["name"], "description": t.get("description", ""), "input_schema": t.get("parameters") or {"type": "object", "properties": {}}}
            for t in tools if t.get("type") == "function"]


def _user_blocks(content) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content or "(empty)"}]
    blocks = []
    for part in content or []:
        if part.get("type") in ("input_text", "text"):
            blocks.append({"type": "text", "text": part.get("text") or "(empty)"})
        elif part.get("type") == "input_image":
            match = re.match(r"data:([^;]+);base64,(.*)", part.get("image_url") or "", re.S)
            if match:
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": match.group(1), "data": match.group(2)}})
    return blocks


def _messages(items: list[dict]) -> list[dict]:
    """Responses history -> Messages. Tool results and the images that follow them share one user turn, results first."""
    messages: list[dict] = []

    def user_turn() -> list:
        if not messages or messages[-1]["role"] != "user":
            messages.append({"role": "user", "content": []})
        return messages[-1]["content"]

    for item in items:
        if not isinstance(item, dict) or item.get("_derived"):
            continue
        if item.get("type") == "anthropic_assistant":
            messages.append({"role": "assistant", "content": item["content"]})
        elif item.get("type") == "function_call_output":
            turn = user_turn()
            result = {"type": "tool_result", "tool_use_id": item["call_id"], "content": str(item.get("output") or "(empty)")}
            first_other = next((i for i, b in enumerate(turn) if b.get("type") != "tool_result"), len(turn))
            turn.insert(first_other, result)  # tool results come before any text or image in the turn
        elif item.get("role") == "user":
            user_turn().extend(_user_blocks(item.get("content")))
        elif item.get("role") == "assistant":  # plain assistant text (never produced by this backend, tolerated)
            messages.append({"role": "assistant", "content": [{"type": "text", "text": str(item.get("content"))}]})
    return messages


CUT_OFF = ("Your last reply reached the output limit before it finished, so its unfinished tool call was dropped. Continue from where you are "
           "in smaller steps: one tool call per reply for large content (write the page with write_file, then refine it with edit_file).")


def _complete_blocks(message) -> list[dict]:
    """A reply cut off at max_tokens may end in an unfinished tool call or an unsigned thinking block: keep only what can be sent back."""
    blocks = [block.model_dump(mode="json", exclude_none=True) for block in message.content]
    if message.stop_reason != "max_tokens":
        return blocks
    kept = [b for b in blocks if b["type"] not in ("tool_use",) and not (b["type"] == "thinking" and not b.get("signature"))]
    return kept


def _stream_with_retry(key: str, request: dict):
    """The SDK retries a request that fails to start; a stream that breaks halfway (the peer closing the connection mid-body)
    is retried here, from the same request: nothing of the broken reply was kept."""
    import time
    for attempt in range(4):
        try:
            with _client(key).messages.stream(**request) as stream:
                return stream.get_final_message()
        except (anthropic.APIConnectionError, anthropic.InternalServerError, anthropic.RateLimitError) as exc:
            if attempt == 3:
                raise
            time.sleep(20 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001 - the transport's own protocol errors surface unwrapped from the stream iterator
            if "RemoteProtocolError" not in type(exc).__name__ and "ReadError" not in type(exc).__name__ or attempt == 3:
                raise
            time.sleep(20 * (attempt + 1))


def respond(payload: dict, key: str) -> dict:
    model = payload["model"]
    request = {
        "model": model,
        "max_tokens": 128000,
        "system": [{"type": "text", "text": payload.get("instructions") or "", "cache_control": {"type": "ephemeral"}}],
        "messages": _messages(payload.get("input") or []),
        "tools": _tools(payload.get("tools") or []),
        "cache_control": {"type": "ephemeral"},  # automatic breakpoint at the end of the conversation
    }
    effort = (payload.get("reasoning") or {}).get("effort")
    if effort:
        request["output_config"] = {"effort": effort}
    output: list[dict] = []
    totals = {"fresh": 0, "written": 0, "read": 0, "out": 0}
    for attempt in range(3):
        message = _stream_with_retry(key, request)
        u = message.usage
        totals["fresh"] += u.input_tokens or 0
        totals["written"] += u.cache_creation_input_tokens or 0
        totals["read"] += u.cache_read_input_tokens or 0
        totals["out"] += u.output_tokens or 0
        raw = _complete_blocks(message)
        sizes = [(b["type"], len(b.get("text") or b.get("thinking") or json.dumps(b.get("input") or ""))) for b in raw]
        if raw:
            output.append({"type": "anthropic_assistant", "content": raw, "stop_reason": message.stop_reason, "sizes": sizes})
        if message.stop_reason != "max_tokens" or attempt == 2:
            break
        nudge = {"role": "user", "content": CUT_OFF}  # appended, never edited: the history stays append-only
        output.append(nudge)
        if raw:
            request["messages"] = request["messages"] + [{"role": "assistant", "content": raw}]
        request["messages"] = request["messages"] + [{"role": "user", "content": [{"type": "text", "text": CUT_OFF}]}]
    texts = [b.text for b in message.content if b.type == "text" and b.text]
    if texts:
        output.append({"type": "message", "_derived": True, "content": [{"type": "output_text", "text": "\n".join(texts)}]})
    if message.stop_reason == "refusal":
        details = getattr(message, "stop_details", None)
        output.append({"type": "message", "_derived": True, "content": [{"type": "output_text", "text": f"[refused: {getattr(details, 'category', None)}]"}]})
    for block in message.content if message.stop_reason != "max_tokens" else []:  # a cut-off call's input is incomplete: never run it
        if block.type == "tool_use":
            output.append({"type": "function_call", "_derived": True, "call_id": block.id, "name": block.name, "arguments": json.dumps(block.input, ensure_ascii=False)})

    fresh, written, read = totals["fresh"], totals["written"], totals["read"]
    price = PRICES.get(model)
    usage = {"input_tokens": fresh + written + read, "input_tokens_details": {"cached_tokens": read, "cache_write_tokens": written},
             "output_tokens": totals["out"], "output_tokens_details": {"reasoning_tokens": 0}}
    if price:
        usage["cost"] = fresh * price["input"] + written * price["cache_write"] + read * price["cache_read"] + usage["output_tokens"] * price["output"]
    return {"id": message.id, "output": output, "usage": usage, "stop_reason": message.stop_reason}
