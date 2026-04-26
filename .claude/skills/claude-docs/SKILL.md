---
name: claude-docs
description: Read Claude / MCP documentation. Use when answering questions about building MCP servers for Claude, Claude connector authentication, OAuth flows for MCP, transport protocols (Streamable HTTP / SSE), tool/prompt/resource limits, or connecting Claude to local MCP servers. Covers anything in the "I need to know how Claude expects MCP servers to behave" space.
---

# Claude / MCP documentation

Local reference material lives in `reference_material/claude/`. Read these files first — they are the canonical source for this project. If a topic is not covered locally, fetch the upstream URL listed below.

## Local files

- `reference_material/claude/building_custom_connectors.md` — Overview of building MCP servers for Claude. Covers supported transports (Streamable HTTP, legacy HTTP+SSE), supported protocol features (tools, prompts, resources, text/image/binary results), unsupported features (sampling, resource subscriptions), tool result size limits, and timeout constraints. **Start here for any MCP server design question.**
- `reference_material/claude/authentication.md` — Claude Code authentication setup (Pro/Max, Teams/Enterprise, Console, Bedrock/Vertex/Foundry). This is about logging *into* Claude Code, not auth *between* Claude and an MCP server.
- `reference_material/claude/connect_to_local_mcp_servers.md` — How users add a local MCP server to Claude Desktop. Useful for Phase 1 testing when running FastMCP locally.

## Upstream URLs (use WebFetch when local docs are insufficient)

- Claude docs index: `https://claude.com/docs/llms.txt`
- Claude Code docs index: `https://code.claude.com/docs/llms.txt`
- MCP spec index: `https://modelcontextprotocol.io/llms.txt`
- MCP authorization spec (latest): `https://modelcontextprotocol.io/specification/latest/basic/authorization`
- Connector authentication reference: `https://claude.com/docs/connectors/building/authentication`

## How to use

1. For any MCP-server-on-Claude question, read the relevant local file in full before answering or designing.
2. If the local file references a topic in more depth (`/connectors/building/authentication`, etc.), resolve it against the Claude docs URL and WebFetch only if needed.
3. Surface concrete constraints (size limits, timeouts, supported transports) when they affect the design — they are easy to miss and expensive to discover late.
