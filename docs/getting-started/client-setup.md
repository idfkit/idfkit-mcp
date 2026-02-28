# MCP Client Setup

This page shows how to connect `idfkit-mcp` to every major MCP client.
All clients run the same underlying command — only the config file location differs.

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

## Transport Options

- Local desktop clients (Claude Desktop, Cursor, VS Code, etc.): use `stdio` (default).
- Hosted deployments: use `streamable-http` and expose a reachable host/port.

---

## Claude Desktop

[Claude Desktop](https://claude.ai/download) was the first MCP client and remains one of the most popular.

Config file:

=== "macOS"

    ```text
    ~/Library/Application Support/Claude/claude_desktop_config.json
    ```

=== "Windows"

    ```text
    %APPDATA%\Claude\claude_desktop_config.json
    ```

=== "Linux"

    ```text
    ~/.config/Claude/claude_desktop_config.json
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

[Cursor](https://cursor.com/) supports MCP servers via a global config file.

Config file:

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

[VS Code](https://code.visualstudio.com/) supports MCP servers through workspace settings or a project-level config file.

Workspace settings (`settings.json`):

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

Or create a `.vscode/mcp.json` in your project root:

```json
{
  "servers": {
    "idfkit": {
      "command": "uvx",
      "args": ["--from", "idfkit-mcp", "idfkit-mcp"]
    }
  }
}
```

## Claude Code (CLI)

[Claude Code](https://docs.anthropic.com/en/docs/claude-code) is Anthropic's CLI tool.
MCP servers can be configured globally or per-project.

Add via CLI:

```bash
claude mcp add idfkit -- uvx --from idfkit-mcp idfkit-mcp
```

Or edit the config files directly.

Project-level config (`.mcp.json` in project root — version-controllable):

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

Global config (`~/.claude.json`):

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

Verify with `claude mcp list` or type `/mcp` inside a session.

## Windsurf

[Windsurf](https://codeium.com/windsurf) (by Codeium) uses the same JSON format as Cursor.

Config file:

```text
~/.codeium/windsurf/mcp_config.json
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

Restart Windsurf after saving.

## ChatGPT Desktop

[ChatGPT](https://openai.com/chatgpt/desktop/) supports MCP servers via a local config file.

Config file:

=== "macOS"

    ```text
    ~/Library/Application Support/com.openai.chat/mcp.json
    ```

=== "Windows"

    ```text
    %APPDATA%\com.openai.chat\mcp.json
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

Restart ChatGPT after saving.

## Codex

In [Codex](https://openai.com/index/introducing-codex/), add a new MCP server pointing to `idfkit-mcp` (or the `uvx` wrapper command).

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

## JetBrains IDEs

IntelliJ IDEA, PyCharm, WebStorm, and other [JetBrains](https://www.jetbrains.com/) IDEs (2025.1+) support MCP servers natively.

1. Open **Settings > Tools > AI Assistant > MCP Servers**.
2. Click **+** to add a new server.
3. Set the command to `uvx` and arguments to `--from idfkit-mcp idfkit-mcp`.

Alternatively, add to the project-level `.idea/mcpServers.json`:

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

!!! tip
    JetBrains can import servers from your Claude Desktop config automatically via **Import from Claude**.

## Cline

[Cline](https://github.com/cline/cline) is a VS Code extension with its own MCP settings panel.

1. Open the Cline sidebar in VS Code.
2. Click the **MCP Servers** icon (plug icon).
3. Click **Configure MCP Servers** to open `cline_mcp_settings.json`.

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

Save the file and Cline will detect the new server automatically.

## Continue

[Continue](https://continue.dev/) is a VS Code / JetBrains extension for AI-assisted coding.

Config file:

```text
~/.continue/config.yaml
```

Example (YAML):

```yaml
mcpServers:
  - name: idfkit
    command: uvx
    args:
      - "--from"
      - idfkit-mcp
      - idfkit-mcp
```

Alternatively, in `~/.continue/config.json`:

```json
{
  "mcpServers": [
    {
      "name": "idfkit",
      "command": "uvx",
      "args": ["--from", "idfkit-mcp", "idfkit-mcp"]
    }
  ]
}
```

## Zed

[Zed](https://zed.dev/) supports MCP servers via its settings file.

Open **Zed > Settings** (or `~/.config/zed/settings.json`) and add:

```json
{
  "context_servers": {
    "idfkit": {
      "command": {
        "path": "uvx",
        "args": ["--from", "idfkit-mcp", "idfkit-mcp"]
      }
    }
  }
}
```

!!! note
    Zed uses `context_servers` instead of `mcpServers` as the top-level key.

---

## Operational Tips

- Prefer absolute paths when loading or saving models.
- Keep one modeling task per server session to avoid state confusion.
- Use `batch_add_objects` when agents need to create many objects.
- Capture outputs in files if your client truncates long tool responses.
