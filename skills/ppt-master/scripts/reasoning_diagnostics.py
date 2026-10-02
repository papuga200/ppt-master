"""Offline-reviewable recorder for exposed summaries; never invokes a model.

Raw CLI capture remains authoritative. This sidecar preserves parsed provider
events verbatim as JSON data, including opaque fields without decoding them.
"""
from copy import deepcopy
from pathlib import Path
import json

SUMMARY_SETTINGS = {"auto", "concise", "detailed", "none"}


def summary_argv(argv, requested=None):
    """Leave defaults unchanged; add only the explicit summary setting."""
    result = list(argv)
    if requested is not None:
        if requested not in SUMMARY_SETTINGS:
            raise ValueError("reasoning summary must be auto, concise, detailed, none or unset")
        result += ["-c", f'model_reasoning_summary="{requested}"']
    return result


class Recorder:
    def __init__(self, requested=None, *, model=None, catalog_default=None,
                 path=None, invocation_id=None):
        summary_argv([], requested)  # validate without changing model support
        self.requested = requested
        self.records = []
        self.active_tools = {}
        self.last_tool_started = None
        self.last_tool_finished = None
        self.finished = False
        self.terminal_event = None
        self.provider_errors = []
        self.path = Path(path) if path is not None else None
        self.metadata = {"schema": "provider-reasoning-diagnostics/v1",
                         "requested_setting": requested,
                         "requested": requested not in (None, "none"),
                         "model": model, "catalog_default": catalog_default,
                         "model_support_override": None,
                         "invocation_id": invocation_id}

    def _append(self, record):
        record = deepcopy(record)
        record['invocation_id'] = self.metadata['invocation_id']
        self.records.append(record)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as out:
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
        return deepcopy(record)

    def observe(self, event, received_at):
        """Use the SAME receive timestamp as the host tool event mapper.

        Clock order is observed receipt order, not private thought timing or
        proof that a summary caused a later tool call. No speculative labeling
        of agent messages as hidden reasoning, plans or retrospective reports.
        """
        event = deepcopy(event)
        if not isinstance(event, dict):
            raise ValueError("Provider event must be a JSON object")
        kind = event.get("type")
        item = event.get("item") or (event.get("payload") if kind == "response_item" else {}) or {}
        if not isinstance(item, dict):
            raise ValueError("Provider item must be a JSON object")
        itype = item.get("type")
        key = item.get("id") or item.get("call_id")
        texts = []
        category = "other_provider_event"
        if itype in {"mcp_tool_call", "command_execution", "function_call", "function_call_output"}:
            category = "tool_event"
            if kind == "item.started":
                self.active_tools[key] = {"id": key, "started_at": received_at,
                                          "tool": item.get("tool") or item.get("command")}
                self.last_tool_started = deepcopy(self.active_tools[key])
            elif kind == "item.completed":
                started = self.active_tools.pop(key, {"id": key, "started_at": None})
                self.last_tool_finished = dict(started, finished_at=received_at)
        elif itype == "reasoning":
            category = "provider_reasoning_item_without_exposed_summary"
            # The Codex CLI's reasoning text is exposed summary text. Responses
            # items expose summary[].summary_text, never opaque encrypted data.
            if isinstance(kind, str) and kind.startswith("item.") and isinstance(item.get("text"), str):
                texts.append(item["text"])
            if "summary" in item and not isinstance(item["summary"], list):
                raise ValueError("Provider reasoning summary must be an array")
            for part in item.get("summary") or []:
                if isinstance(part, dict) and part.get("type") == "summary_text" and isinstance(part.get("text"), str):
                    texts.append(part["text"])
            if any(t.strip() for t in texts):
                category = "exposed_provider_summary"
            elif item.get("encrypted_content") is not None:
                category = "opaque_provider_reasoning"
        elif kind in {"response.reasoning_summary_text.delta", "response.reasoning_summary_text.done"}:
            text = event.get("delta") if kind.endswith(".delta") else event.get("text")
            texts = [text] if isinstance(text, str) else []
            category = "exposed_provider_summary" if any(t.strip() for t in texts) else "empty_provider_summary_event"
        elif itype in {"agent_message", "message"}:
            category = "visible_authored_message_unclassified"
        if kind in {"turn.completed", "turn.failed"}:
            self.finished = True
            self.terminal_event = {"type": kind, "received_at": received_at}
        if kind in {"turn.failed", "error"}:
            self.provider_errors.append(deepcopy(event))
        record = {"event_sequence": len(self.records), "received_at": received_at,
                  "provider_timestamp": event.get("timestamp"),
                  "category": category, "summary_text": texts,
                  "active_tool_ids": list(self.active_tools),
                  "last_tool_started": deepcopy(self.last_tool_started),
                  "last_tool_finished": deepcopy(self.last_tool_finished),
                  "provider_event": event}
        return self._append(record)

    def visible_record(self, content, provenance, received_at):
        """Label explicit sidecars; never infer these roles from prose."""
        if provenance not in {"visible_authored_plan", "retrospective_self_report"}:
            raise ValueError("explicit visible provenance required")
        return self._append({"event_sequence": len(self.records),
                             "received_at": received_at, "category": provenance,
                             "summary_text": [], "content": deepcopy(content),
                             "provider_event": None})

    def receipt(self):
        observed = [r for r in self.records if r["category"] == "exposed_provider_summary"]
        return dict(self.metadata,
                    actual_availability="observed" if observed else "not_observed" if self.finished else "pending",
                    observed_summary_events=len(observed),
                    capture_complete=self.finished,
                    terminal_event=deepcopy(self.terminal_event),
                    provider_errors=deepcopy(self.provider_errors),
                    note="Events can repeat summaries or contain deltas; event count is not unique thought count. Opaque data is retained, never decoded.")

    def finish(self, receipt_path):
        # Do not mark the provider turn complete when only capture has stopped.
        Path(receipt_path).write_text(json.dumps(self.receipt(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
