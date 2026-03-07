# Codex CLI Session Format

Codex CLI stores session transcripts as JSONL files on disk. Each line is a self-contained JSON object representing one event in the session.

## File Location

```
~/.codex/sessions/YYYY/MM/DD/rollout-{timestamp}-{uuid}.jsonl
```

Sessions are organized by date. Each file represents one interactive session or rollout.

## Event Structure

Every line has at minimum:

```json
{
  "timestamp": "ISO8601",
  "type": "session_meta | response_item | event_msg | turn_context",
  "payload": { ... }
}
```

## Event Types

### `session_meta`

Always the first line. Contains session-level metadata.

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | string | ISO8601 session start time |
| `type` | string | `"session_meta"` |
| `session_id` | string | UUID for the session |
| `cwd` | string | Working directory at session start |
| `model` | string | Model identifier (e.g. `"o4-mini"`) |
| `git` | object | Git state: `{ branch, commit, dirty }` |

### `response_item`

Core content events. The `payload` object determines the subtype.

#### Message subtypes (`payload.type = "message"`)

| Role | Description |
|------|-------------|
| `developer` | System/developer prompt |
| `user` | User-provided input |
| `assistant` | Model-generated response |

Message content is in `payload.content[]`, each element having:
- `type`: `"input_text"` or `"output_text"`
- `text`: The actual text content

#### `function_call`

A tool invocation by the model.

| Field | Type | Description |
|-------|------|-------------|
| `payload.type` | string | `"function_call"` |
| `payload.name` | string | Tool name (e.g. `"shell"`, `"apply_diff"`) |
| `payload.call_id` | string | Unique call identifier |
| `payload.arguments` | string | JSON-encoded arguments |

#### `function_call_output`

Result of a tool invocation.

| Field | Type | Description |
|-------|------|-------------|
| `payload.type` | string | `"function_call_output"` |
| `payload.call_id` | string | Matches the `function_call` call_id |
| `payload.output` | string | Tool output content |

#### `custom_tool_call` / `custom_tool_call_output`

Extended tool types for file changes and command execution. These carry structured data beyond simple text output.

**File changes** (`fileChange`):
- `path`: Absolute file path
- `kind`: `"create"`, `"modify"`, or `"delete"`
- `diff`: Unified diff of the change

**Command execution** (`commandExecution`):
- `command`: The shell command
- `exitCode`: Process exit code
- `status`: `"pass"` or `"fail"`
- `output`: Command stdout/stderr (may be truncated)

#### `reasoning`

Model reasoning traces.

| Field | Type | Description |
|-------|------|-------------|
| `payload.type` | string | `"reasoning"` |
| `payload.summary` | string | Human-readable reasoning summary |
| `payload.encrypted` | boolean | If true, content is not accessible |

### `event_msg`

Lifecycle and status events. The `payload.msg_type` field determines the subtype.

| msg_type | Description |
|----------|-------------|
| `task_started` | Agent task begins |
| `task_complete` | Agent task ends |
| `user_message` | User sent a message |
| `agent_message` | Agent produced output |
| `agent_reasoning` | Agent reasoning step |
| `token_count` | Token usage statistics (skip during normalization) |

### `turn_context`

Context snapshots taken at turn boundaries. Contains the model's accumulated context including file contents, plan state, and conversation history. Useful for understanding what information the model had available at each decision point.

## Additional Event Patterns

### Aggregate Diffs (`turn/diff/updated`)

Session-level cumulative diffs emitted at turn boundaries. These show the total file changes since session start — high value for understanding the overall outcome.

### Plan Updates (`turn/plan/updated`)

Agent plan state changes. Track how the agent's strategy evolved during the session.

### Context Compaction (`contextCompaction`)

Marks where the model's context window was compressed. Important for walkthroughs because it indicates where the agent's "memory" was summarized — details before a compaction event may not have been available to the agent for later decisions.
