# Use Annona from AI assistants (MCP)

Annona is an [MCP](https://modelcontextprotocol.io) server: any MCP client can read your profile
and pantry, search products and prices, and build your weekly plan. Instructions verified against
each client's official documentation on 2026-11-21.

## Tools

| Tool | Does | Writes |
|---|---|---|
| `get_profile` | members, daily targets, diet, allergies, preferences, budget, kitchen | no |
| `get_pantry` | what you have at home | no |
| `update_pantry` | set / add / remove up to 20 items | **yes** |
| `search_products` | products with prices and unit prices (`detail=full`: nutrition, allergens) | no |
| `get_prices` | latest price and history for up to 20 products | no |
| `build_weekly_plan` | optimise the shop and generate the menu (background, ~1 min) | **yes** |
| `get_plan` | the menu or its generation status (`detail=full`: steps, portions) | no |
| `recipe_of_the_day` | a day's meals with portions; with `slot`, that meal's detailed recipe (steps, heat, times) | stores the recipe |
| `cook_meal` | preview, then (`confirm=true`) mark a meal cooked and deduct the pantry | **yes** |
| `shopping_list` | the week's list with packs, prices and total | no |

Writing tools are marked as such, so clients ask for your confirmation before running them.

### Why so few tools (and no "code mode")

Every tool definition is sent to the model on every turn. Current practice (Anthropic, "Writing
tools for agents"; Cloudflare, "Code Mode") is to keep that small: tools that complete a whole
workflow instead of thin database calls, one-line descriptions, compact paginated answers with a
`concise`/`full` switch, and errors that say what to do next. Cloudflare's "search + execute"
code mode pays off for APIs with thousands of endpoints (it gives agents the whole Cloudflare API
in about 1,000 tokens); Annona's ten tools cost about the same (**~1,240 tokens**, measured with
`uv run python scripts/mcp_tool_tokens.py`), so running model-written code on your server would
add risk without saving tokens. The single registry (`server/annona_server/tools/`) keeps that
option open if the tool count grows.

## Transports

- **stdio** (same computer as the server): `uv run python -m annona_server.mcp_server`. Uses the
  database in `ANNONA_DATABASE_URL`.
- **Streamable HTTP**: `http://<server>:8000/mcp` on the running API, with the header
  `Authorization: Bearer <ANNONA_API_TOKEN>`.

## Claude Code

```bash
# local (stdio)
claude mcp add --transport stdio annona -- uv --directory /path/to/Annona run python -m annona_server.mcp_server
# or over your network (HTTP)
claude mcp add --transport http annona http://192.168.1.20:8000/mcp --header "Authorization: Bearer YOUR_TOKEN"
```

Check with `claude mcp get annona` or `/mcp` inside Claude Code.

## Claude Desktop

Edit `claude_desktop_config.json` (macOS `~/Library/Application Support/Claude/`, Windows
`%APPDATA%\Claude\`, Linux `~/.config/Claude/`) and restart Claude Desktop:

```json
{
  "mcpServers": {
    "annona": {
      "command": "uv",
      "args": ["--directory", "/path/to/Annona", "run", "python", "-m", "annona_server.mcp_server"]
    }
  }
}
```

## Gemini CLI

In `~/.gemini/settings.json` (avoid underscores in the server name):

```json
{
  "mcpServers": {
    "annona": {
      "command": "uv",
      "args": ["--directory", "/path/to/Annona", "run", "python", "-m", "annona_server.mcp_server"]
    },
    "annona-remote": {
      "httpUrl": "http://192.168.1.20:8000/mcp",
      "headers": { "Authorization": "Bearer YOUR_TOKEN" }
    }
  }
}
```

## claude.ai (web) and ChatGPT: need a public HTTPS server

Both connect from their companies' cloud, so they cannot reach a server on your home network:

- **claude.ai custom connectors** (Customize > Connectors > Add custom connector): the server
  must be reachable over HTTPS on port 443; a fixed bearer token can be set under "Request
  headers".
- **ChatGPT**: custom MCP servers need a public HTTPS endpoint; full support is for Business and
  Enterprise/Edu workspaces on the web (Pro: read-only); OpenAI recommends OAuth.

Exposing Annona to the Internet safely (HTTPS, and OAuth for ChatGPT) is planned for Phase 15.

## Testing with the MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv run python -m annona_server.mcp_server
```

Open the URL it prints, list the tools and call them.

## Privacy

Tool results go to the AI provider behind your client (Anthropic, OpenAI, Google). They include
your profile, pantry and plans; nothing else leaves your server.
