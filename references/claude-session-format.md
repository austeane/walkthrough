# Claude Code Session Format

Claude Code stores session transcripts as JSONL files on disk. Each line is a self-contained JSON object representing one record in the conversation.

## File Locations

**Main session files:**
```
~/.claude/projects/{encoded-cwd}/{sessionId}.jsonl
```

The `{encoded-cwd}` is the working directory path with path separators replaced (e.g. `-Users-austin-dev-myproject`).

**Subagent transcripts:**
```
~/.claude/projects/{encoded-cwd}/{sessionId}/subagents/{subagentId}.jsonl
```

Subagent transcripts follow the same record format but represent work delegated to child agent instances (e.g. via the Agent tool with `model: "haiku"`).

## Record Types

Every line has a `type` field. The primary types are:

### `user`

User input or tool results returned to the model.

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | `"user"` |
| `parentUuid` | string | Links to parent message |
| `isSidechain` | boolean | Whether this is a side conversation |
| `userType` | string | User type identifier |
| `cwd` | string | Working directory |
| `sessionId` | string | Session UUID |
| `version` | string | Claude Code version |
| `gitBranch` | string | Current git branch |
| `slug` | string | Model slug |
| `message` | object | Content payload |

The `message.content` field is either a string or a list of content objects:
- `{ "type": "text", "text": "..." }` — User text input
- `{ "type": "tool_result", "tool_use_id": "...", "content": ... }` — Tool execution result

### `assistant`

Model-generated responses.

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | `"assistant"` |
| `parentUuid` | string | Links to parent message |
| `isSidechain` | boolean | Whether this is a side conversation |
| `message` | object | Content payload |
| `message.model` | string | Model identifier |
| `message.id` | string | Message UUID |
| `requestId` | string | API request identifier |

The `message.content` is a list of content objects:

- **Text**: `{ "type": "text", "text": "..." }` — Assistant text output
- **Tool use**: `{ "type": "tool_use", "id": "...", "name": "...", "input": {...} }` — Tool invocation
- **Thinking**: `{ "type": "thinking", "thinking": "..." }` — Model reasoning (extended thinking)

### `file-history-snapshot`

Captures file state at a point in time. Used for tracking file evolution during a session.

| Field | Type | Description |
|-------|------|-------------|
| `type` | string | `"file-history-snapshot"` |
| `files` | object | Map of file paths to content snapshots |

### `progress`

Internal progress tracking records. Skipped during normalization.

### `queue-operation`

Message queue management records. Skipped during normalization.

### `system`

System-level messages (e.g. context window management, session lifecycle).

## Tool Types in Claude Code

Claude Code uses a rich set of tools. Common ones relevant to walkthroughs:

| Tool Name | Description | Key Input Fields |
|-----------|-------------|------------------|
| `Read` | Read file contents | `file_path` |
| `Write` | Create/overwrite a file | `file_path`, `content` |
| `Edit` | Apply string replacement | `file_path`, `old_string`, `new_string` |
| `Bash` | Execute shell command | `command` |
| `Glob` | Find files by pattern | `pattern` |
| `Grep` | Search file contents | `pattern`, `path` |
| `Agent` | Spawn subagent | `prompt`, `model` |

## Diff Reconstruction

Claude Code does not emit explicit file change events like Codex. File changes are reconstructed from tool calls during normalization:

- **`Edit` tool**: Has `old_string` and `new_string` in `input` — produces a `file_change` with `kind: "modify"` and a synthetic diff
- **`Write` tool**: Has `file_path` and `content` in `input` — produces a `file_change` with `kind: "create"` or `"overwrite"`
- **`Bash` tool**: May contain file-modifying commands (`sed`, `mv`, etc.) — these are captured as `command` events but diffs are not reconstructed (requires git diffing for full coverage)

## Subagent Handling

Subagent transcripts are child sessions spawned by the parent via the `Agent` tool. During normalization:

- The parent session's `tool_use` that spawned the subagent is identified
- Subagent events are linked via `parent_call_id` (the spawning tool call) and `root_turn_index` (which turn in the parent session triggered it)
- All subagent events carry the `agent_id` field identifying the child agent
- Subagent transcripts may be missing initial user prompts (known limitation) — the parent invocation's context is used as fallback
