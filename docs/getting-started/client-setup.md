# MCP Client Setup

This page shows practical server configurations for common MCP clients.

## Common Command

All clients ultimately need to run:

```bash
idfkit-mcp
```

or

```bash
uvx --from idfkit-mcp idfkit-mcp
```

Use `uvx` when you want a managed, versioned runtime without installing into a project environment.

## Codex

In Codex, add a new MCP server pointing to `idfkit-mcp` (or the `uvx` wrapper command).

Recommended command:

```bash
uvx --from idfkit-mcp idfkit-mcp
```

Recommended working directory:

- The repository where IDF/epJSON files and simulation outputs should live.

Recommended prompt behavior:

- Start sessions with `get_model_summary`.
- Call `describe_object_type` before object creation or updates.
- Validate after every edit batch.

## Claude Desktop

Add an `idfkit` server entry to Claude Desktop MCP config.

macOS config file:

```text
~/Library/Application Support/Claude/claude_desktop_config.json
```

Example:

```json
{
  "mcpServers": {
    "idfkit": {
      "command": "uvx",
      "args": ["--from", "idfkit-mcp", "idfkit-mcp"]
    }
  }
}
```

Restart Claude Desktop after saving.

## Cursor

Cursor MCP config file:

```text
~/.cursor/mcp.json
```

Example:

```json
{
  "mcpServers": {
    "idfkit": {
      "command": "uvx",
      "args": ["--from", "idfkit-mcp", "idfkit-mcp"]
    }
  }
}
```

## VS Code

Workspace settings example:

```json
{
  "mcp.servers": {
    "idfkit": {
      "command": "uvx",
      "args": ["--from", "idfkit-mcp", "idfkit-mcp"]
    }
  }
}
```

## Operational Tips

- Prefer absolute paths when loading or saving models.
- Keep one modeling task per server session to avoid state confusion.
- Use `batch_add_objects` when agents need to create many objects.
- Capture outputs in files if your client truncates long tool responses.
