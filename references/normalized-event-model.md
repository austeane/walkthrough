# Normalized Event Model

The normalized event model is the common schema that all provider-specific session formats are converted into. It serves as the single input format for chunking, summarization, and walkthrough assembly.

## File Format

One JSON object per line (JSONL). Produced by `normalize_codex.py` or `normalize_claude.py`, consumed by `chunk_events.py` and the summarization agents.

## Event Schema

```json
{
  "seq": 1,
  "source_line": 42,
  "source_path": "/path/to/session.jsonl",
  "provider": "codex",
  "session_id": "uuid-string",
  "ts": "2026-03-01T14:30:00Z",
  "kind": "tool_use",
  "turn_index": 3,
  "agent_id": null,
  "parent_call_id": null,
  "root_turn_index": null,
  "text": "primary text content",
  "tool": {
    "name": "shell",
    "call_id": "call_abc123",
    "input": {},
    "output": "command output",
    "is_error": false
  },
  "file_change": {
    "path": "src/auth.ts",
    "kind": "modify",
    "diff": "--- a/src/auth.ts\n+++ b/src/auth.ts\n..."
  },
  "command": {
    "cmd": "npm test",
    "exit_code": 0,
    "status": "pass",
    "output_preview": "All 42 tests passed",
    "output_lines": 150
  },
  "meta": {
    "cwd": "/Users/dev/project",
    "model": "o4-mini",
    "git": { "branch": "main", "commit": "abc1234" }
  }
}
```

**Only non-null fields are included in output.** A `user_message` event will not have `tool`, `file_change`, `command`, or `meta` fields.

## Field Reference

### Envelope Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `seq` | integer | yes | Monotonically increasing sequence number across the serialized normalized artifact |
| `source_line` | integer | yes | Line number in the source JSONL file (1-indexed) |
| `source_path` | string | yes | Absolute path to the source JSONL file |
| `provider` | string | yes | `"codex"` or `"claude"` |
| `session_id` | string | yes | Session UUID from the source |
| `ts` | string | yes | ISO8601 timestamp |
| `kind` | string | yes | Event kind (see below) |
| `turn_index` | integer | yes | Increments on each visible `user_message` event within its conversational stream |

### Subagent Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `agent_id` | string | no | Set for events from a subagent |
| `parent_call_id` | string | no | The tool call ID in the parent session that spawned this subagent |
| `root_turn_index` | integer | no | Turn index in the parent session when the subagent was spawned |
| `parent_link_status` | string | no | `matched`, `ambiguous`, or `unavailable` |
| `parent_link_basis` | string | no | How the parent link was resolved (`progress`, `single`, or `time`) |

### Content Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | string | no | Primary text content (message text, reasoning, etc.) |
| `tool` | object | no | Present for `tool_use` and `tool_result` kinds |
| `file_change` | object | no | Present for `file_change` kind |
| `command` | object | no | Present for `command` kind |
| `meta` | object | no | Present for `meta` kind only |
| `media` | object | no | Present for `screenshot` kind |

## Event Kinds

| Kind | Description | Typical Content Fields |
|------|-------------|----------------------|
| `meta` | Session metadata (first event) | `meta` |
| `user_message` | User input | `text` |
| `assistant_message` | Model text output | `text` |
| `tool_use` | Tool invocation | `tool` (name, call_id, input) |
| `tool_result` | Tool output | `tool` (call_id, output, is_error) |
| `file_change` | File modification | `file_change` (path, kind, diff) |
| `command` | Shell command execution | `command` (cmd, exit_code, status) |
| `reasoning` | Model reasoning trace | `text` |
| `turn_context` | Context snapshot at turn boundary | `text` |
| `file_snapshot` | File state capture | `text` |
| `system` | System-level event | `text` |
| `aggregate_diff` | Cumulative diff at turn boundary (Codex) | `text` |
| `plan_update` | Agent plan state change (Codex) | `text` |
| `screenshot` | Screenshot captured during session | `media` |
| `compaction` | Context window compression marker (Codex `compacted`) | `text` |

## Tool Object

```json
{
  "name": "string — tool name (e.g. shell, Edit, apply_diff)",
  "call_id": "string — unique identifier linking tool_use to tool_result",
  "input": "object — tool arguments (structure varies by tool)",
  "output": "string — tool output text",
  "is_error": "boolean — true if the tool execution failed"
}
```

For `tool_use` events: `name`, `call_id`, and `input` are populated.
For `tool_result` events: `call_id`, `output`, and `is_error` are populated.

## File Change Object

```json
{
  "path": "string — relative or absolute file path",
  "kind": "create | modify | delete",
  "diff": "string — unified diff format (may be synthetic for Claude Code)"
}
```

Generated directly from Codex `fileChange` events. For Claude Code, reconstructed from `Edit` (old_string/new_string) and `Write` (full content) tool calls.

## Command Object

```json
{
  "cmd": "string — the shell command executed",
  "exit_code": "integer — process exit code",
  "status": "pass | fail — derived from exit_code (0 = pass)",
  "output_preview": "string — first ~500 chars of output",
  "output_lines": "integer — total line count of output"
}
```

## Meta Object

```json
{
  "cwd": "string — working directory",
  "model": "string — model identifier",
  "git": {
    "branch": "string",
    "commit": "string",
    "dirty": "boolean",
    "repository_url": "string"
  }
}
```

Present only on the first event (`kind: "meta"`) of each normalized file.

## Media Object

```json
{
  "data_b64": "string — base64-encoded image data",
  "mime_type": "string — MIME type (e.g. image/png, image/jpeg)",
  "width": "integer — image width in pixels",
  "height": "integer — image height in pixels",
  "context": "string — description of what was being shown",
  "tool_name": "string — tool that captured the screenshot (e.g. computer)",
  "source": "session | file — how the screenshot was obtained"
}
```

Present only on `screenshot` events.

## Turn Indexing

The `turn_index` field uses **1-based indexing** for user turns:

- `turn_index = 0`: Reserved for the initial `meta` event (before any user interaction)
- `turn_index = 1`: First visible `user_message` and all subsequent events until the next visible user message
- `turn_index = N`: Nth user message and its associated events

Both providers (Codex and Claude) follow this convention. The `turn_index` increments each time a visible `user_message` event with text content is encountered. Blank user payloads and Claude `user` records containing only `tool_result` content do not increment the turn.

This enables:

- Grouping events by conversational turn
- Understanding which user request triggered which agent actions
- Chunking at turn boundaries for cleaner LLM context
- Consistent turn counting across providers (`max(turn_index)` equals the number of user turns)

## Subagent Linking

For sessions with subagents (Claude Code), the normalized output interleaves parent and child events in timestamp order. Validation and turn semantics are applied per conversational stream, not globally across all interleaved events. Subagent events are distinguished by:

- `agent_id`: Non-null string identifying the child agent
- `parent_call_id`: The `tool.call_id` of the Agent tool invocation in the parent
- `root_turn_index`: The `turn_index` in the parent session when the subagent was spawned
- `parent_link_status`: Whether the parent link was matched confidently, ambiguous, or unavailable
- `parent_link_basis`: Whether the link came from explicit progress metadata or a deterministic fallback

This allows downstream consumers to reconstruct the parent-child relationship and understand delegation patterns while preserving honest uncertainty when linkage is ambiguous.
