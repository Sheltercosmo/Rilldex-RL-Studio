"""Lossless role/call extraction for recorded chat messages.

This reads supplied source records only. Tool schemas are declarations, not proof
of execution. Private task scenarios and reference answers are not messages.
"""
import json

from .schema import InputError, event, content_text


def append_messages(document, events, warnings, *, portable=False, message_field='messages', nullable_calls=False, flat_tool_definitions=False, unlinked_agent_results=False):
    messages, tools = document.get(message_field), document.get("tools", [])
    if not isinstance(messages, list) or not messages or any(not isinstance(m, dict) for m in messages):
        raise InputError('/'+message_field+' must be a nonempty list of objects')
    if not isinstance(tools, list) or any(not isinstance(t, dict) for t in tools):
        raise InputError("/tools must be a list of objects")
    definitions = {}
    for i, tool in enumerate(tools):
        function = tool.get("function")
        flat = (flat_tool_definitions and 'type' not in tool and 'function' not in tool
                and isinstance(tool.get('name'),str) and bool(tool['name'].strip())
                and isinstance(tool.get('parameters'),dict))
        if flat:
            name=tool['name']
        elif tool.get("type") == "function" and isinstance(function, dict) and isinstance(function.get("name"), str):
            name=function['name']
        else:
            raise InputError("Tool definitions require a named function")
        if name in definitions:
            raise InputError("Duplicate tool definition")
        definitions[name] = {"source_pointer": f"/tools/{i}", "definition": tool}
        if flat:definitions[name]['source_format']='bfcl-function/1'
    seen_calls = {}
    for i, message in enumerate(messages):
        pointer = f"/{message_field}/{i}"
        role, text = message.get("role"), message.get("content")
        if role not in ({"system", "developer", "user", "assistant", "tool"} if portable else {"system", "user", "assistant", "tool"}):
            raise InputError(f"Unsupported source role at {pointer}")
        media=[]
        if portable:
            if isinstance(text,list) and any(not isinstance(p,dict) or not isinstance(p.get('type'),str) for p in text):
                raise InputError('Content parts require an explicit type; unsupported parts must not disappear')
            text,media=content_text(text)
            if media:warnings.append('Media references are preserved; image/audio contents have not been inspected.')
        elif not isinstance(text, str):
            raise InputError(f"{pointer}/content must be text; media or null content needs an explicit adapter")
        calls = message.get("tool_calls", [])
        if (nullable_calls or portable) and calls is None: calls=[]
        if not isinstance(calls, list) or any(not isinstance(c, dict) for c in calls):
            raise InputError(f"{pointer}/tool_calls must be a list of objects")
        if calls and role not in {"assistant", "user"}:
            raise InputError("Tool calls require an assistant or user requestor")
        common = {"source_message_index": i, "source_role": role}
        if portable:common['media']=media
        if role == "tool":
            cid = message.get("tool_call_id")
            if (not isinstance(cid, str) or not cid) and not ((portable or unlinked_agent_results) and cid is None):
                raise InputError("Tool feedback requires an explicit call identifier")
            requestor = seen_calls.get(cid)
            if requestor is None:
                warnings.append("A tool result has no preceding source call; it remains unlinked.")
            if (portable or unlinked_agent_results) and requestor is None:
                # This contract is the supplied model conversation, not a full
                # simulator log. The visible result remains unlinked.
                requestor='assistant'
            # A full simulator trace can include customer-side calls/results
            # that the monitored assistant did not observe. Keep them out of its
            # prefix until the customer actually communicates the information.
            event(events, kind="feedback" if requestor == "assistant" else "external_feedback",
                  text=text, pointer=pointer+"/content", actor="environment", requestor=requestor,
                  agent_visibility="recorded_agent_result" if requestor == "assistant" else "not_established",
                  source_call_id=cid, feedback_origin="environment", tool=message.get("name"), **common)
            continue
        parent = event(events, kind="external_message" if role == "user" and calls else {"system":"context", "developer":"context", "user":"instruction", "assistant":"message"}[role],
                       actor="agent" if role == "assistant" else role, text=text, pointer=pointer+"/content", **common)
        if role == "system":
            parent["context_kind"] = "recorded_system_message"
        if portable and message.get('reasoning_content') is not None:
            if role!='assistant' or not isinstance(message['reasoning_content'],str):raise InputError('reasoning_content must be recorded assistant text')
            event(events,kind='reasoning',actor='agent',text=message['reasoning_content'],pointer=pointer+'/reasoning_content',parent_id=parent['id'])
        for j, call in enumerate(calls):
            cid, function = call.get("id"), call.get("function")
            if not (portable and cid is None) and (not isinstance(cid, str) or not cid or cid in seen_calls):
                raise InputError("Assistant call identifiers must be nonempty and unique")
            if call.get("type") != "function" or not isinstance(function, dict) or not isinstance(function.get("name"), str):
                raise InputError("Only named function calls are supported")
            name, raw = function["name"], function.get("arguments")
            structured=portable and isinstance(raw,dict)
            if not isinstance(raw, str) and not structured:
                raise InputError("Recorded function arguments must be a JSON string")
            # Invalid generated arguments are behavior evidence, not an ingestion failure.
            try:
                def reject_nonfinite(value):
                    raise ValueError('Non-finite JSON argument: '+value)
                arguments = raw if structured else json.loads(raw, parse_constant=reject_nonfinite)
                if not isinstance(arguments, dict):
                    raise ValueError("not an argument object")
                argument_status = "json_object"
            except ValueError:
                arguments, argument_status = {"unparsed_arguments": raw}, "invalid_json_object"
                warnings.append("A recorded call has invalid JSON-object arguments; the exact attempted payload is preserved.")
            if cid is not None:seen_calls[cid] = role
            elif portable:warnings.append('A tool call has no native ID; its result linkage is unestablished.')
            action = event(events, kind="action" if role == "assistant" else "external_action",
                           actor="agent" if role == "assistant" else "user",
                           agent_visibility="model_authored" if role == "assistant" else "not_established",
                           text=f"{name}({json.dumps(raw,ensure_ascii=False) if structured else raw})", pointer=f"{pointer}/tool_calls/{j}",
                           call_id=cid, tool=name, arguments=arguments, raw_arguments=raw,
                           argument_status=argument_status, parent_id=parent["id"],
                           extraction="recorded-function-call", **common)
            if name in definitions:
                action["tool_contract"] = definitions[name]
            elif role == "assistant":
                warnings.append("A called tool has no supplied definition; tool semantics may be incomplete.")
            if role == "user":
                warnings.append("Customer-side tool calls and their results are preserved as external events; they are excluded from assistant behavior counts and prefix evidence. Later user messages remain observable claims.")


def apb_metadata(document):
    """Validate source identity without leaking reference labels into behavior."""
    if not isinstance(document.get("data_source"), str) or not document["data_source"]:
        raise InputError("AgentProcessBench requires data_source")
    for field in ("query_index", "sample_index", "total_index"):
        if isinstance(document.get(field), bool) or not isinstance(document.get(field), int):
            raise InputError(f"AgentProcessBench requires integer {field}")
    labels = document.get("step_labels")
    if not isinstance(labels, dict):
        raise InputError("AgentProcessBench requires a step_labels object")
    messages = document["messages"]
    for index, label in labels.items():
        if (not isinstance(index, str) or not index.isascii() or not index.isdigit()
                or index!=str(int(index)) or int(index) >= len(messages) or messages[int(index)]["role"] != "assistant"):
            raise InputError("A reference step label must point to an assistant message")
        if type(label) is not int or label not in {-1, 0, 1}:
            raise InputError("Reference process labels must be -1, 0 or 1")
    source = document["data_source"]
    return {"task_id": f"{source}:query-{document['query_index']}", "sample_id": document["sample_index"],
            "source_record_id": document["total_index"], "environment": source,
            "environment_family": "search_and_retrieval" if source.startswith("searchR1_") else
                                  "tool_and_business_workflows" if source.startswith("tau2_") else "unrecorded",
            "source_collection": "AgentProcessBench"}
