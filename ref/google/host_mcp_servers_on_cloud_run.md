# Deploy MCP servers in AgentCore Runtime
<a name="runtime-mcp"></a>

Amazon Bedrock AgentCore Runtime lets you deploy and run Model Context Protocol (MCP) servers in the AgentCore Runtime. This guide walks you through creating, testing, and deploying your first MCP server.

For an example, see [https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/01-tutorials/01-AgentCore-runtime/02-hosting-MCP-server](https://github.com/awslabs/amazon-bedrock-agentcore-samples/tree/main/01-tutorials/01-AgentCore-runtime/02-hosting-MCP-server).

In this section, you learn:
+ How to create an MCP server with tools
+ How to test your server locally
+ How to deploy your server to AWS 
+ How to invoke your deployed server

For more information about MCP, see [MCP protocol contract](runtime-mcp-protocol-contract.md).

**Topics**
+ [How Amazon Bedrock AgentCore supports MCP](#runtime-mcp-how-it-works)
+ [Prerequisites](#runtime-mcp-prerequisites)
+ [Step 1: Create your MCP server](#runtime-mcp-create-server)
+ [Step 2: Test your MCP server locally](#runtime-mcp-test-locally)
+ [Step 3: Deploy your MCP server to AWS](#runtime-mcp-deploy-aws)
+ [Step 4: Invoke your deployed MCP server](#runtime-mcp-invoke-server)
+ [Authentication Error Responses for OAuth-Configured Agents](#runtime-mcp-auth-error-responses)
+ [End to End Flow with Auth0](#runtime-mcp-auth0-flow)
+ [Appendix](#runtime-mcp-appendix)

## How Amazon Bedrock AgentCore supports MCP
<a name="runtime-mcp-how-it-works"></a>

When you configure a Amazon Bedrock AgentCore Runtime with the MCP protocol, the service expects MCP server containers to be available at the path `0.0.0.0:8000/mcp` , which is the default path supported by most official MCP server SDKs.

Amazon Bedrock AgentCore supports both stateless and stateful streamable-HTTP MCP servers. By default, stateless mode ( `stateless_http=True` ) is recommended for basic MCP servers. The platform automatically adds an `Mcp-Session-Id` header for any request without one, so MCP clients can maintain connection continuity to the same Amazon Bedrock AgentCore Runtime session.

For MCP servers that require multi-turn interactions (elicitation), LLM-generated content (sampling), or progress notifications, stateful mode ( `stateless_http=False` ) enables these capabilities. In stateful mode, the runtime preserves MCP session state across requests within the same invocation. For more information, see [Stateful MCP server features](mcp-stateful-features.md).

The payload of the [InvokeAgentRuntime](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_InvokeAgentRuntime.html) API is passed through directly, allowing RPC messages of protocols like MCP to be easily proxied.

## Prerequisites
<a name="runtime-mcp-prerequisites"></a>
+ Python 3.10 or higher installed and basic understanding of Python
+ An AWS account with appropriate permissions and local credentials configured

## Step 1: Create your MCP server
<a name="runtime-mcp-create-server"></a>

### Install required packages
<a name="runtime-mcp-install-packages"></a>

First, install the MCP package:

```
pip install mcp
```

### Create your first MCP server
<a name="runtime-mcp-create-first-server"></a>

Create a new file called `my_mcp_server.py` :

```
# my_mcp_server.py

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse

mcp = FastMCP(host="0.0.0.0", stateless_http=True)

@mcp.tool()
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together"""
    return a + b

@mcp.tool()
def multiply_numbers(a: int, b: int) -> int:
    """Multiply two numbers together"""
    return a * b

@mcp.tool()
def greet_user(name: str) -> str:
    """Greet a user by name"""
    return f"Hello, {name}! Nice to meet you."

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

### Understanding the code
<a name="runtime-mcp-code-explanation"></a>
+  **FastMCP** : Creates an MCP server that can host your tools
+  **@mcp.tool()** : Decorator that turns your Python functions into MCP tools
+  **Tools** : Three simple tools that demonstrate different types of operations
+  **stateless\$1http=True** : Configures the server in stateless mode, which is the default for basic MCP servers

**Tip**  
For MCP servers that require multi-turn interactions (elicitation) or LLM-generated content (sampling), use `stateless_http=False` to enable stateful mode. Stateful MCP servers maintain session context across multiple requests within the same tool invocation. For more information, see [Stateful MCP server features](mcp-stateful-features.md).

## Step 2: Test your MCP server locally
<a name="runtime-mcp-test-locally"></a>

### Start your MCP server
<a name="runtime-mcp-start-server"></a>

Run your MCP server locally:

```
python my_mcp_server.py
```

You should see output indicating the server is running on port `8000`.

### Test with MCP client
<a name="runtime-mcp-test-client"></a>

From a new terminal, create a new file `my_mcp_client.py` and execute it using `python my_mcp_client.py` 

```
# my_mcp_client.py

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    mcp_url = "http://localhost:8000/mcp"
    headers = {}

    async with streamablehttp_client(mcp_url, headers, timeout=120, terminate_on_close=False) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tool_result = await session.list_tools()
            print(tool_result)

asyncio.run(main())
```

You can also test your server using the MCP Inspector as described in [Local testing with MCP inspector](#runtime-mcp-appendix-b).

## Step 3: Deploy your MCP server to AWS
<a name="runtime-mcp-deploy-aws"></a>

### Install deployment tools
<a name="runtime-mcp-install-deployment-tools"></a>

Install the AgentCore CLI:

```
npm install -g @aws/agentcore
```

You use the AgentCore CLI to deploy your agent to AgentCore Runtime.

Create a project folder with the following structure:

```
## Project Folder Structure

your_project_directory/
├── mcp_server.py # Your main agent code
├── requirements.txt # Dependencies for your agent
└── __init__.py # Makes the directory a Python package
```

Create a new file called `requirements.txt` , add the following to it:

```
mcp
```

 `requirements.txt` specifies the requirements that the agent needs for deployment to AgentCore Runtime.

### Create your project for deployment
<a name="runtime-mcp-configure-deployment"></a>

Before creating your project, you need to set up a Cognito user pool for authentication as described in [Set up Cognito user pool for authentication](#runtime-mcp-appendix-a) . This provides the OAuth tokens required for secure access to your deployed server.

**Note**  
Starting **October 7, 2025** , Amazon Bedrock AgentCore uses a Service-Linked Role for workload identity permissions when using OAuth authentication. For detailed information about this change, see [Identity service-linked role](service-linked-roles.md#identity-service-linked-role).

After setting up authentication, scaffold a new project with MCP protocol:

```
agentcore create --protocol MCP
```

Follow the interactive prompts to provide a project name. The CLI scaffolds the project structure including an `agentcore/agentcore.json` configuration file. Copy your `my_mcp_server.py` file into the generated project’s agent code directory, and ensure the entrypoint in `agentcore/agentcore.json` points to your server file.

### Deploy to AWS
<a name="runtime-mcp-deploy"></a>

Deploy your agent:

```
agentcore deploy
```

This command will:

1. Package your agent code and dependencies

1. Upload the deployment artifact to Amazon S3

1. Create a Amazon Bedrock AgentCore runtime

1. Deploy your agent to AWS 

After deployment, you’ll receive an agent runtime ARN that looks like:

```
arn:aws:bedrock-agentcore:us-west-2:accountId:runtime/my_mcp_server-xyz123
```

## Step 4: Invoke your deployed MCP server
<a name="runtime-mcp-invoke-server"></a>

### Test with MCP client (remote)
<a name="runtime-mcp-test-remote"></a>

Before testing, set the following environment variables:
+ Export agent ARN as an environment variable: `export AGENT_ARN="agent_arn"` 
+ Export bearer token as an environment variable: `export BEARER_TOKEN="bearer_token"` 

if you pass in an `Accept` header, it must follow the [MCP](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#sending-messages-to-the-server) standard. Acceptable media types are `application/json` and `text/event-stream`.

Create a new file `my_mcp_client_remote.py` and execute it using `python my_mcp_client_remote.py` 

```
import asyncio
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    agent_arn = os.getenv('AGENT_ARN')
    bearer_token = os.getenv('BEARER_TOKEN')
    if not agent_arn or not bearer_token:
        print("Error: AGENT_ARN or BEARER_TOKEN environment variable is not set")
        sys.exit(1)

    encoded_arn = agent_arn.replace(':', '%3A').replace('/', '%2F')
    mcp_url = f"https://bedrock-agentcore.us-west-2.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"
    headers = {"authorization": f"Bearer {bearer_token}","Content-Type":"application/json"}
    print(f"Invoking: {mcp_url}, \nwith headers: {headers}\n")

    async with streamablehttp_client(mcp_url, headers, timeout=120, terminate_on_close=False) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tool_result = await session.list_tools()
            print(tool_result)

asyncio.run(main())
```

You can also test your deployed server using the MCP Inspector as described in [Remote testing with MCP inspector](#runtime-mcp-appendix-c).

## Authentication Error Responses for OAuth-Configured Agents
<a name="runtime-mcp-auth-error-responses"></a>

OAuth-configured agents follow [RFC 6749 (OAuth 2.0)](https://datatracker.ietf.org/doc/html/rfc6749) authentication standards. When authentication is missing, the service returns a 401 Unauthorized response with a WWW-Authenticate header (per [RFC 7235](https://datatracker.ietf.org/doc/html/rfc7235) ), enabling clients to discover the authorization server endpoints through the GetRuntimeProtectedResourceMetadata API.

### 401 Unauthorized - Missing Authentication
<a name="runtime-mcp-auth-401-unauthorized"></a>

When no Bearer token is provided in the Authorization header, the response is:

```
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer resource_metadata="https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{ESCAPED_ARN}/invocations/.well-known/oauth-protected-resource?qualifier={QUALIFIER}"
```

## End to End Flow with Auth0
<a name="runtime-mcp-auth0-flow"></a>

This section demonstrates OAuth authentication using Auth0 as the identity provider. We use Auth0 for this example because it supports **Dynamic Client Registration (DCR)** , which simplifies the client setup process by allowing clients to register themselves programmatically at runtime.

### Step 1 - Step 3: Create and test your MCP server
<a name="runtime-mcp-auth0-steps-1-3"></a>

Follow Steps 1-3 from [Step 1: Create your MCP server](#runtime-mcp-create-server) through [Step 3: Deploy your MCP server to AWS](#runtime-mcp-deploy-aws) to create and test your MCP server.

### Step 4: Create Auth0 application
<a name="runtime-mcp-auth0-step-4"></a>

Follow the Auth0 setup instructions at [Auth0 by Okta](identity-idp-auth0.md).

 **Enable Dynamic Client Registration:** 

1. Dashboard → Settings → Advanced

1. Toggle "OIDC Dynamic Application Registration" → ON

1. Save changes

For more information, see [Auth0 Dynamic Client Registration documentation](https://auth0.com/docs/get-started/applications/dynamic-client-registration).

### Step 5: Create your project for deployment
<a name="runtime-mcp-auth0-step-5"></a>

After setting up authentication, scaffold a new project with MCP protocol:

```
agentcore create --protocol MCP
```

Follow the interactive prompts to provide a project name. The CLI scaffolds the project structure including an `agentcore/agentcore.json` configuration file. Copy your `my_mcp_server.py` file into the generated project’s agent code directory, and ensure the entrypoint in `agentcore/agentcore.json` points to your server file.

### Step 6: Deploy to AWS
<a name="runtime-mcp-auth0-step-6"></a>

Deploy your agent:

```
agentcore deploy
```

This command will:
+ Package your agent code and dependencies
+ Upload the deployment artifact to Amazon S3
+ Create a Amazon Bedrock AgentCore runtime
+ Deploy your agent to AWS 

After deployment, you’ll receive an agent runtime ARN that looks like:

```
arn:aws:bedrock-agentcore:us-west-2:accountId:runtime/my_mcp_server-xyz123
```

### Step 7: Invoke your deployed Agent
<a name="runtime-mcp-auth0-step-7"></a>

This client is based on the [official MCP SDK simple-auth-client example](https://github.com/modelcontextprotocol/python-sdk/blob/main/examples/clients/simple-auth-client/mcp_simple_auth_client/main.py) with Auth0-specific modifications.

**Note**  
When using Auth0 with Dynamic Client Registration, you must include the `audience` parameter in authorization requests to receive JWT tokens. Without this parameter, Auth0 returns opaque tokens or JWE (encrypted) tokens instead of standard JWT tokens. The MCP SDK sends OAuth 2.0’s `resource` parameter (RFC 8707), but Auth0 requires the OIDC `audience` parameter for JWT tokens. Both parameters serve similar purposes but Auth0 prioritizes `audience` . For more information, see [Auth0 Community - JWT tokens with Dynamic Application Registration](https://community.auth0.com/t/jwt-tokens-with-dynamic-application-registration/189741).

Create a file named `mcp_auth0_client.py` with the following code. This client handles Auth0-specific requirements including the audience parameter:

**Note**  
The code includes httpx patching to inject User-Agent headers into all HTTP requests. This is necessary because the MCP Python SDK currently does not include User-Agent headers in its HTTP requests, which can cause issues with AWS WAF rules that require User-Agent headers. For more information, see [MCP Python SDK Issue \$11664](https://github.com/modelcontextprotocol/python-sdk/issues/1664) and [AWS WAF managed rule groups](https://docs.aws.amazon.com/waf/latest/developerguide/aws-managed-rule-groups-baseline.html).

#### MCP Python Auth0 Client Code
<a name="runtime-mcp-auth0-client-code"></a>

```
#!/usr/bin/env python3
"""
MCP client with OAuth authentication support for Auth0.

Based on the official MCP SDK simple-auth-client example with Auth0 compatibility.
Adds support for Auth0's 'audience' parameter requirement.

Usage:
    # Required
    export AGENT_ARN="arn:aws:bedrock:us-west-2:123456789012:agent/ABCD1234"

    # Required for Auth0
    export AUTH0_API_IDENTIFIER="your-api-identifier"

    # Optional - custom endpoint for beta/dev environments
    export CUSTOM_ENDPOINT="https://beta.example.com"

    python mcp_auth0_client.py

The client will automatically:
- Encode the Agent ARN for use in the URL
- Construct the MCP invocation endpoint URL
- Add Auth0 'audience' parameter to authorization requests (when using Auth0)
- Work with any OAuth 2.0 compliant identity provider
"""

import asyncio
import httpx
import os
import threading
import time
import webbrowser
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# Patch httpx at the request level to inject User-Agent header
# This ensures ALL HTTP requests have the User-Agent header, including OAuth discovery calls
_original_httpx_request = httpx.Request.__init__

def _patched_httpx_request_init(self, method, url, *args, **kwargs):
    """Patched Request.__init__ that injects User-Agent header into all HTTP requests."""
    # Get or create headers
    headers = kwargs.get('headers')
    if headers is None:
        headers = {}
        kwargs['headers'] = headers

    # Convert to mutable dict if needed
    if not isinstance(headers, dict):
        headers = dict(headers)
        kwargs['headers'] = headers

    # Inject User-Agent if not present (case-insensitive check)
    if 'User-Agent' not in headers and 'user-agent' not in headers:
        headers['User-Agent'] = 'python-mcp-sdk/1.0 (BedrockAgentCore-Runtime)'

    # Call original __init__
    _original_httpx_request(self, method, url, *args, **kwargs)

# Apply the patch globally before importing MCP modules
httpx.Request.__init__ = _patched_httpx_request_init

# Now import MCP modules - they will use patched httpx
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

class InMemoryTokenStorage(TokenStorage):
    """Simple in-memory token storage implementation."""

    def __init__(self):
        self._tokens: OAuthToken | None = None
        self._client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self._tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self._client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_info = client_info

class CallbackHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler to capture OAuth callback."""

    def __init__(self, request, client_address, server, callback_data):
        """Initialize with callback data storage."""
        self.callback_data = callback_data
        super().__init__(request, client_address, server)

    def do_GET(self):
        """Handle GET request from OAuth redirect."""
        parsed = urlparse(self.path)
        query_params = parse_qs(parsed.query)

        if "code" in query_params:
            self.callback_data["authorization_code"] = query_params["code"][0]
            self.callback_data["state"] = query_params.get("state", [None])[0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"""
            <html>
            <body>
                <h1>Authorization Successful!</h1>
                <p>You can close this window and return to the terminal.</p>
                <script>setTimeout(() => window.close(), 2000);</script>
            </body>
            </html>
            """)
        elif "error" in query_params:
            self.callback_data["error"] = query_params["error"][0]
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                f"""
            <html>
            <body>
                <h1>Authorization Failed</h1>
                <p>Error: {query_params["error"][0]}</p>
                <p>You can close this window and return to the terminal.</p>
            </body>
            </html>
            """.encode()
            )
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Suppress default logging."""
        pass

class CallbackServer:
    """Simple server to handle OAuth callbacks."""

    def __init__(self, port=3030):
        self.port = port
        self.server = None
        self.thread = None
        self.callback_data = {"authorization_code": None, "state": None, "error": None}

    def _create_handler_with_data(self):
        """Create a handler class with access to callback data."""
        callback_data = self.callback_data

        class DataCallbackHandler(CallbackHandler):
            def __init__(self, request, client_address, server):
                super().__init__(request, client_address, server, callback_data)

        return DataCallbackHandler

    def start(self):
        """Start the callback server in a background thread."""
        handler_class = self._create_handler_with_data()
        self.server = HTTPServer(("localhost", self.port), handler_class)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        print(f"🖥️  Started callback server on http://localhost:{self.port}")

    def stop(self):
        """Stop the callback server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1)

    def wait_for_callback(self, timeout=300):
        """Wait for OAuth callback with timeout."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.callback_data["authorization_code"]:
                return self.callback_data["authorization_code"]
            elif self.callback_data["error"]:
                raise Exception(f"OAuth error: {self.callback_data['error']}")
            time.sleep(0.1)
        raise Exception("Timeout waiting for OAuth callback")

    def get_state(self):
        """Get the received state parameter."""
        return self.callback_data["state"]

def add_auth0_audience_parameter(authorization_url: str, audience: str) -> str:
    """
    Add Auth0 'audience' parameter to authorization URL.

    Auth0 requires the 'audience' parameter to identify which API's token settings
    to use. Without it, Auth0 returns opaque tokens or JWE instead of JWT.

    This function properly adds the audience parameter while preserving all existing
    query parameters (including the OAuth 'resource' parameter).

    Args:
        authorization_url: The authorization URL from the OAuth flow
        audience: The Auth0 API identifier (e.g., "runtime-api")

    Returns:
        Modified URL with audience parameter added

    Reference:
        https://auth0.com/docs/secure/tokens/access-tokens/get-access-tokens
    """
    # Only apply to Auth0 URLs that don't already have audience
    if 'auth0.com' not in authorization_url or 'audience=' in authorization_url:
        return authorization_url

    # Parse URL and query parameters
    parsed = urlparse(authorization_url)
    query_params = parse_qs(parsed.query, keep_blank_values=True)

    # Add audience parameter
    query_params['audience'] = [audience]

    # Rebuild URL with new parameter
    new_query = urlencode(query_params, doseq=True)
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))

class SimpleAuthClient:
    """Simple MCP client with Auth0 OAuth support."""

    def __init__(
        self,
        server_url: str,
        transport_type: str = "streamable-http",
        auth0_audience: str | None = None,
    ):
        self.server_url = server_url
        self.transport_type = transport_type
        self.auth0_audience = auth0_audience
        self.session: ClientSession | None = None

    async def connect(self):
        """Connect to the MCP server."""
        print(f"🔗 Attempting to connect to {self.server_url}...")

        try:
            callback_server = CallbackServer(port=3030)
            callback_server.start()

            async def callback_handler() -> tuple[str, str | None]:
                """Wait for OAuth callback and return auth code and state."""
                print("⏳ Waiting for authorization callback...")
                try:
                    auth_code = callback_server.wait_for_callback(timeout=300)
                    return auth_code, callback_server.get_state()
                finally:
                    callback_server.stop()

            client_metadata_dict = {
                "client_name": "MCP Auth0 Client",
                "redirect_uris": ["http://localhost:3030/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            }

            async def redirect_handler(authorization_url: str) -> None:
                """Redirect handler that opens the URL in a browser with Auth0 audience parameter."""
                # Add Auth0 audience parameter if configured
                if self.auth0_audience:
                    authorization_url = add_auth0_audience_parameter(
                        authorization_url,
                        self.auth0_audience
                    )

                webbrowser.open(authorization_url)

            print("\n🔧 Creating OAuth client provider...")
            # Create OAuth authentication handler
            # Note: httpx.AsyncClient is globally patched to inject User-Agent header
            oauth_auth = OAuthClientProvider(
                server_url=self.server_url,
                client_metadata=OAuthClientMetadata.model_validate(client_metadata_dict),
                storage=InMemoryTokenStorage(),
                redirect_handler=redirect_handler,
                callback_handler=callback_handler,
            )
            print("🔧 OAuth client provider created successfully")

            # Create transport with auth handler based on transport type
            if self.transport_type == "sse":
                print("📡 Opening SSE transport connection with auth...")
                async with sse_client(
                    url=self.server_url,
                    auth=oauth_auth,
                    timeout=60,
                ) as (read_stream, write_stream):
                    await self._run_session(read_stream, write_stream, None)
            else:
                print("📡 Opening StreamableHTTP transport connection with auth...")
                async with streamablehttp_client(
                    url=self.server_url,
                    auth=oauth_auth,
                    timeout=timedelta(seconds=60),
                ) as (read_stream, write_stream, get_session_id):
                    await self._run_session(read_stream, write_stream, get_session_id)

        except Exception as e:
            print(f"❌ Failed to connect: {e}")
            import traceback
            traceback.print_exc()

    async def _run_session(self, read_stream, write_stream, get_session_id):
        """Run the MCP session with the given streams."""
        print("🤝 Initializing MCP session...")
        async with ClientSession(read_stream, write_stream) as session:
            self.session = session
            print("⚡ Starting session initialization...")
            await session.initialize()
            print("✨ Session initialization complete!")

            print(f"\n✅ Connected to MCP server at {self.server_url}")
            if get_session_id:
                session_id = get_session_id()
                if session_id:
                    print(f"Session ID: {session_id}")

            # Run interactive loop
            await self.interactive_loop()

    async def list_tools(self):
        """List available tools from the server."""
        if not self.session:
            print("❌ Not connected to server")
            return

        try:
            result = await self.session.list_tools()
            if hasattr(result, "tools") and result.tools:
                print("\n📋 Available tools:")
                for i, tool in enumerate(result.tools, 1):
                    print(f"{i}. {tool.name}")
                    if tool.description:
                        print(f"   Description: {tool.description}")
                    print()
            else:
                print("No tools available")
        except Exception as e:
            print(f"❌ Failed to list tools: {e}")

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None):
        """Call a specific tool."""
        if not self.session:
            print("❌ Not connected to server")
            return

        try:
            result = await self.session.call_tool(tool_name, arguments or {})
            print(f"\n🔧 Tool '{tool_name}' result:")
            if hasattr(result, "content"):
                for content in result.content:
                    if content.type == "text":
                        print(content.text)
                    else:
                        print(content)
            else:
                print(result)
        except Exception as e:
            print(f"❌ Failed to call tool '{tool_name}': {e}")

    async def interactive_loop(self):
        """Run interactive command loop."""
        print("\n🎯 Interactive MCP Client")
        print("Commands:")
        print("  list - List available tools")
        print("  call <tool_name> [args] - Call a tool")
        print("  quit - Exit the client")
        print()

        while True:
            try:
                command = input("mcp> ").strip()

                if not command:
                    continue

                if command == "quit":
                    break

                elif command == "list":
                    await self.list_tools()

                elif command.startswith("call "):
                    parts = command.split(maxsplit=2)
                    tool_name = parts[1] if len(parts) > 1 else ""

                    if not tool_name:
                        print("❌ Please specify a tool name")
                        continue

                    # Parse arguments (simple JSON-like format)
                    arguments = {}
                    if len(parts) > 2:
                        import json
                        try:
                            arguments = json.loads(parts[2])
                        except json.JSONDecodeError:
                            print("❌ Invalid arguments format (expected JSON)")
                            continue

                    await self.call_tool(tool_name, arguments)

                else:
                    print("❌ Unknown command. Try 'list', 'call <tool_name>', or 'quit'")

            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                break
            except EOFError:
                break

async def main():
    """Main entry point."""
    # Get Agent ARN from environment
    agent_arn = os.getenv("AGENT_ARN")

    if not agent_arn:
        print("❌ Please set AGENT_ARN environment variable")
        print("Example: export AGENT_ARN='arn:aws:bedrock:us-west-2:123456789012:agent/ABCD1234'")
        return

    # Encode the ARN for use in URL
    encoded_arn = agent_arn.replace(':', '%3A').replace('/', '%2F')

    # Get base URL - use custom endpoint or default to production
    base_endpoint = os.getenv("CUSTOM_ENDPOINT", "https://bedrock-agentcore.us-west-2.amazonaws.com")

    # Construct MCP URL from encoded ARN (no qualifier - SDK discovers it from PRM API)
    server_url = f"{base_endpoint}/runtimes/{encoded_arn}/invocations"

    # Get Auth0 configuration (required only for Auth0)
    auth0_audience = os.getenv("AUTH0_API_IDENTIFIER")

    # Get optional transport type
    transport_type = os.getenv("MCP_TRANSPORT_TYPE", "streamable-http")

    print("🚀 MCP Auth0 Client")
    print(f"Agent ARN: {agent_arn}")
    print(f"Endpoint: {base_endpoint}")
    print(f"Connecting to: {server_url}")
    print(f"Transport type: {transport_type}")
    if auth0_audience:
        print(f"Auth0 audience: {auth0_audience}")

    # Start connection flow - OAuth will be handled automatically
    client = SimpleAuthClient(
        server_url,
        transport_type,
        auth0_audience,
    )
    await client.connect()

def cli():
    """CLI entry point for uv script."""
    asyncio.run(main())

if __name__ == "__main__":
    cli()
```

To use the client:

1. Set required environment variables:

   ```
   export AGENT_ARN="arn:aws:bedrock:us-west-2:123456789012:agent/ABCD1234"
   ```

1. Set Auth0-specific environment variable (required only for Auth0):

   ```
   export AUTH0_API_IDENTIFIER="your-api-identifier"
   ```

1. Run the client:

   ```
   python mcp_auth0_client.py
   ```

The client will automatically:
+ Encode the Agent ARN for use in the URL
+ Construct the MCP invocation endpoint URL
+ Add Auth0 `audience` parameter to authorization requests (when using Auth0)
+ Work with any OAuth 2.0 compliant identity provider

## Appendix
<a name="runtime-mcp-appendix"></a>

### Set up Cognito user pool for authentication
<a name="runtime-mcp-appendix-a"></a>

Create a new file `setup_cognito.sh` and add the following content.

```
#!/bin/bash

# Create User Pool and capture Pool ID directly
export POOL_ID=$(aws cognito-idp create-user-pool \
  --pool-name "MyUserPool" \
  --policies '{"PasswordPolicy":{"MinimumLength":8}}' \
  --region $REGION | jq -r '.UserPool.Id')

# Create App Client and capture Client ID directly
export CLIENT_ID=$(aws cognito-idp create-user-pool-client \
  --user-pool-id $POOL_ID \
  --client-name "MyClient" \
  --no-generate-secret \
  --explicit-auth-flows "ALLOW_USER_PASSWORD_AUTH" "ALLOW_REFRESH_TOKEN_AUTH" \
  --region $REGION | jq -r '.UserPoolClient.ClientId')

# Create User
aws cognito-idp admin-create-user \
  --user-pool-id $POOL_ID \
  --username $USERNAME \
  --region $REGION \
  --message-action SUPPRESS > /dev/null

# Set Permanent Password
aws cognito-idp admin-set-user-password \
  --user-pool-id $POOL_ID \
  --username $USERNAME \
  --password $PASSWORD \
  --region $REGION \
  --permanent > /dev/null

# Authenticate User and capture Access Token
export BEARER_TOKEN=$(aws cognito-idp initiate-auth \
  --client-id "$CLIENT_ID" \
  --auth-flow USER_PASSWORD_AUTH \
  --auth-parameters USERNAME=$USERNAME,PASSWORD=$PASSWORD \
  --region $REGION | jq -r '.AuthenticationResult.AccessToken')

# Output the required values
echo "Pool id: $POOL_ID"
echo "Discovery URL: https://cognito-idp.$REGION.amazonaws.com/$POOL_ID/.well-known/openid-configuration"
echo "Client ID: $CLIENT_ID"
echo "Bearer Token: $BEARER_TOKEN"
```

Open a terminal window and set the following environment variables:
+  *REGION* – the AWS Region that you want to use
+  *USERNAME* – the user name for the new user
+  *PASSWORD* – the password for the new user

```
export REGION=us-east-1 // set your desired Region
export USERNAME=USER NAME
export PASSWORD=PASSWORD
```

Run the script using the command `source setup_cognito.sh`.

**Note**  
For detailed OAuth authentication setup and Service-Linked Role information, see [Authenticate and authorize with Inbound Auth and Outbound Auth](runtime-oauth.md).

After running this script, note the following values for use in the deployment configuration:
+ Discovery URL: Used during the `agentcore create` step
+ Client ID: Used during the `agentcore create` step
+ Bearer Token: Used when invoking your deployed server

### Local testing with MCP inspector
<a name="runtime-mcp-appendix-b"></a>

The MCP Inspector is a visual tool for testing MCP servers. To use it, you need:
+ Node.js and npm installed

Install and run the MCP Inspector:

```
npx @modelcontextprotocol/inspector
```

This will:
+ Start the MCP Inspector server
+ Display a URL in your terminal (typically `http://localhost:6274` )

To use the Inspector:

1. Navigate to `http://localhost:6274` in your browser

1. Paste the MCP server URL ( `http://localhost:8000/mcp` ) into the MCP Inspector connection field

1. You’ll see your tools listed in the sidebar

1. Click on any tool to test it

1. Fill in the parameters (e.g., for `add_numbers` , enter values for `a` and `b` )

1. Click "Call Tool" to see the result

### Remote testing with MCP inspector
<a name="runtime-mcp-appendix-c"></a>

You can also test your deployed server using the MCP Inspector. First, URL-encode your agent ARN:

```
export AGENT_ARN="arn:aws:bedrock-agentcore:us-west-2:123456789012:runtime/my_mcp_server-xyz123"
echo -n $AGENT_ARN | jq -sRr '@uri'
```

This outputs the URL-encoded ARN:

```
arn%3Aaws%3Abedrock-agentcore%3Aus-west-2%3A123456789012%3Aruntime%2Fmy_mcp_server-xyz123
```

Then connect with the MCP Inspector:

1. Start the MCP Inspector:

   ```
   npx @modelcontextprotocol/inspector
   ```

1. In the web interface:
   + Select "Streamable HTTP" as the transport
   + Enter your agent’s endpoint URL using the encoded ARN. Make sure to use the same region as your agent’s ARN:

     ```
     https://bedrock-agentcore.REGION.amazonaws.com/runtimes/ENCODED_ARN/invocations?qualifier=DEFAULT
     ```

     Example for us-west-2:

     ```
     https://bedrock-agentcore.us-west-2.amazonaws.com/runtimes/arn%3Aaws%3Abedrock-agentcore%3Aus-west-2%3A123456789012%3Aruntime%2Fmy_mcp_server-xyz123/invocations?qualifier=DEFAULT
     ```
   + Add your Bearer token in the Authentication section with header name `Authorization` and value `Bearer YOUR_TOKEN` 
   + Click "Connect"

1. Test your tools just like you did locally


This tutorial shows you how to build and deploy a remote Model Context Protocol (MCP)
server on Cloud Run using the [streamable HTTP transport](https://docs.cloud.google.com/run/docs/host-mcp-servers#host-remote-streamable-http-mcp-servers).
With streamable HTTP transport, the MCP server operates as an independent process that can
handle multiple client connections.

## Objectives

In this tutorial, you will:

1. [Prepare your Python project with the `uv` package manager](https://docs.cloud.google.com/run/docs/tutorials/deploy-remote-mcp-server#install).
2. [Create an MCP server for math operations](https://docs.cloud.google.com/run/docs/tutorials/deploy-remote-mcp-server#create-mcp-server).
3. [Deploy to Cloud Run](https://docs.cloud.google.com/run/docs/tutorials/deploy-remote-mcp-server#deploy).
4. [Authenticate MCP client](https://docs.cloud.google.com/run/docs/tutorials/deploy-remote-mcp-server#authenticate).
5. [Test the remote MCP server](https://docs.cloud.google.com/run/docs/tutorials/deploy-remote-mcp-server#test).

## Costs


In this document, you use the following billable components of Google Cloud:


- [Artifact Registry](https://docs.cloud.google.com/artifact-registry)
- [Cloud Build](https://docs.cloud.google.com/build)
- [Cloud Run](https://docs.cloud.google.com/run)

<br />


To generate a cost estimate based on your projected usage,
use the [pricing calculator](https://docs.cloud.google.com/products/calculator).
New Google Cloud users might be eligible for a [free trial](https://docs.cloud.google.com/free).

<br />

## Before you begin

1.


   Enable the Artifact Registry, Cloud Run Admin API, and Cloud Build APIs.


   **Roles required to enable APIs**


   To enable APIs, you need the Service Usage Admin IAM
   role (`roles/serviceusage.serviceUsageAdmin`), which
   contains the `serviceusage.services.enable` permission. [Learn how to grant
   roles](https://docs.cloud.google.com/iam/docs/granting-changing-revoking-access).

   [Enable the APIs](https://console.cloud.google.com/flows/enableapi?apiid=artifactregistry.googleapis.com,cloudbuild.googleapis.com,run.googleapis.com)
2. [Set up your Cloud Run development environment](https://docs.cloud.google.com/run/docs/setup) in your Google Cloud project.
3. Make sure you have the appropriate [permissions to deploy services](https://docs.cloud.google.com/run/docs/reference/iam/roles#additional-configuration), and the [Cloud Run Admin](https://docs.cloud.google.com/iam/docs/roles-permissions/run#run.admin) (`roles/run.admin`) and [Service Account User](https://docs.cloud.google.com/iam/docs/roles-permissions/iam#iam.serviceAccountUser) (`roles/iam.serviceAccountUser`) roles granted to your account.
4. Grant the [Cloud Run
   Invoker (`roles/run.invoker`)](https://docs.cloud.google.com/run/docs/securing/managing-access#invoker) role to your account. This role allows the remote MCP server to access the Cloud Run service.

#### Learn how to grant the roles

#### Console

1.
   In the Google Cloud console, go to the **IAM** page.

   [Go to IAM](https://console.cloud.google.com/projectselector/iam-admin/iam?supportedpurview=project)
2. Select the project.
3. Click **Grant access**.
4.
   In the **New principals** field, enter your user identifier. This
   is typically the email address used to deploy
   the Cloud Run service.

5. In the **Select a role** list, select a role.
6. To grant additional roles, click **Add
   another role** and add each additional role.
7. Click **Save**.

#### gcloud

To grant the required IAM roles to your account on your
project:

```bash
   gcloud projects add-iam-policy-binding PROJECT_ID \
       --member=PRINCIPAL \
       --role=ROLE
   
```

Replace:

- <var translate="no">PROJECT_NUMBER</var>: your Google Cloud project number.
- <var translate="no">PROJECT_ID</var>: your Google Cloud project ID.
- <var translate="no">PRINCIPAL</var>: the email address of the account to which you are granting the role.
- <var translate="no">ROLE</var>: the role you are adding to the deployer account.
5. If you are under a domain restriction organization policy [restricting](https://docs.cloud.google.com/resource-manager/docs/organization-policy/restricting-domains) unauthenticated invocations for your project, you will need to access your deployed service as described under [Testing private services](https://docs.cloud.google.com/run/docs/triggering/https-request#testing-private).

6. Install [Uv](https://docs.astral.sh/uv/getting-started/installation/), a Python package and project manager.

## Prepare your Python project

The following steps describe how to [set up your Python project with the `uv` package manager](https://docs.astral.sh/uv/getting-started/installation/).

1. Create a folder named `mcp-on-cloudrun` to store the source code for
   deployment:

         mkdir mcp-on-cloudrun
         cd mcp-on-cloudrun

2. Create a Python project with the `uv` tool to generate a `pyproject.toml` file:

         uv init --name "mcp-on-cloudrun" --description "Example of deploying an MCP server on Cloud Run" --bare --python 3.10

   The `uv init` command creates the following `pyproject.toml` file:

       [project]
       name = "mcp-server"
       version = "0.1.0"
       description = "Example of deploying an MCP server on Cloud Run"
       readme = "README.md"
       requires-python = ">=3.10"
       dependencies = []

3. Create the following additional new files:

   - `server.py` for the MCP server source code
   - `test_server.py` to test the remote server
   - A Dockerfile for deploying to Cloud Run

       touch server.py test_server.py Dockerfile

   Your project directory should contain the following structure:

       ├── mcp-on-cloudrun
       │   ├── pyproject.toml
       │   ├── server.py
       │   ├── test_server.py
       │   └── Dockerfile

## Create an MCP server for math operations

To provide valuable context for improving the use of LLMs with MCP, set up a
math MCP server with [FastMCP](https://gofastmcp.com/getting-started/welcome).
FastMCP provides a quick way to build MCP servers and clients with Python.

Follow these steps to create an MCP server for math operations such as
addition and subtraction.

1. Run the following command to add FastMCP as a dependency in the `pyproject.toml` file:

       uv add fastmcp==2.13.1 --no-sync

2. Add the following math MCP server source code in the `server.py` file:

       import asyncio
       import logging
       import os

       from fastmcp import FastMCP 

       logger = logging.getLogger(__name__)
       logging.basicConfig(format="[%(levelname)s]: %(message)s", level=logging.INFO)

       mcp = FastMCP("MCP Server on Cloud Run")

       @mcp.tool()
       def add(a: int, b: int) -> int:
           """Use this to add two numbers together.

           Args:
               a: The first number.
               b: The second number.

           Returns:
               The sum of the two numbers.
           """
           logger.info(f">>> 🛠️ Tool: 'add' called with numbers '{a}' and '{b}'")
           return a + b

       @mcp.tool()
       def subtract(a: int, b: int) -> int:
           """Use this to subtract two numbers.

           Args:
               a: The first number.
               b: The second number.

           Returns:
               The difference of the two numbers.
           """
           logger.info(f">>> 🛠️ Tool: 'subtract' called with numbers '{a}' and '{b}'")
           return a - b

       if __name__ == "__main__":
           logger.info(f"🚀 MCP server started on port {os.getenv('PORT', 8080)}")
           # Could also use 'sse' transport, host="0.0.0.0" required for Cloud Run.
           asyncio.run(
               mcp.run_async(
                   transport="streamable-http",
                   host="0.0.0.0",
                   port=os.getenv("PORT", 8080),
               )
           )

3. Include the following code in the Dockerfile to use the `uv` tool for running the `server.py`
   file:

       # Use the official Python image
       FROM python:3.13-slim

       # Install uv
       COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

       # Install the project into /app
       COPY . /app
       WORKDIR /app

       # Allow statements and log messages to immediately appear in the logs
       ENV PYTHONUNBUFFERED=1

       # Install dependencies
       RUN uv sync

       EXPOSE $PORT

       # Run the FastMCP server
       CMD ["uv", "run", "server.py"]

## Deploy to Cloud Run

You can deploy the MCP server as a [container image](https://docs.cloud.google.com/run/docs/deploying) or as
[source code](https://docs.cloud.google.com/run/docs/deploying-source-code):

### Container image

To deploy an MCP server packaged as a container image, follow these instructions.

1. Create an Artifact Registry repository to store the container image:

       gcloud artifacts repositories create remote-mcp-servers \
       --repository-format=docker \
       --location=us-central1 \
       --description="Repository for remote MCP servers" \
       --project=PROJECT_ID

2. Build the container image and push it to Artifact Registry with Cloud Build:

       gcloud builds submit --region=us-central1 --tag us-central1-docker.pkg.dev/PROJECT_ID/remote-mcp-servers/mcp-server:latest

3. Deploy the MCP server container image to Cloud Run:

       gcloud run deploy mcp-server \
       --image us-central1-docker.pkg.dev/PROJECT_ID/remote-mcp-servers/mcp-server:latest \
       --region=us-central1 \
       --no-allow-unauthenticated

<br />

### Source

You can deploy remote MCP servers to Cloud Run from their sources.

Deploy from source by running the following command:

    gcloud run deploy mcp-server --no-allow-unauthenticated --region=us-central1 --source .

## Authenticate MCP client

If you deployed your service with the `--no-allow-unauthenticated` flag, any MCP client
that connects to your remote MCP server must authenticate.

1. Grant the [Cloud Run Invoker](https://docs.cloud.google.com/run/docs/securing/managing-access#invoker) (`roles/run.invoker`) role to the service account. This
   Identity and Access Management policy binding makes sure that a strong security mechanism is used to authenticate your local MCP client.

2. Run the [Cloud Run proxy](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/proxy)
   to create an authenticated tunnel to the remote MCP server on your local
   machine:

       gcloud run services proxy mcp-server --region=us-central1

   If the Cloud Run proxy is not yet installed, this command prompts
   you to download the proxy. Follow the prompts to download and install the proxy.

Cloud Run authenticates all traffic to `http://127.0.0.1:8080` and forwards
requests to the remote MCP server.

## Test the remote MCP server

You test and connect to the remote MCP server by using the FastMCP client and accessing
the URL `http://127.0.0.1:8080/mcp`.

To test and invoke the add and subtract mechanism, follow these steps:

1. Before running the test server, [run the Cloud Run proxy](https://docs.cloud.google.com/run/docs/tutorials/deploy-remote-mcp-server#authenticate).

2. Create a test file called `test_server.py` and add the following code:

       import asyncio

       from fastmcp import Client


       async def test_server():
           # Test the MCP server using streamable-http transport.
           # Use "/sse" endpoint if using sse transport.
           async with Client("http://localhost:8080/mcp") as client:
               # List available tools
               tools = await client.list_tools()
               for tool in tools:
                   print(f">>> 🛠️  Tool found: {tool.name}")
               # Call add tool
               print(">>> 🪛  Calling add tool for 1 + 2")
               result = await client.call_tool("add", {"a": 1, "b": 2})
               print(f"<<< ✅ Result: {result.content[0].text}")
               # Call subtract tool
               print(">>> 🪛  Calling subtract tool for 10 - 3")
               result = await client.call_tool("subtract", {"a": 10, "b": 3})
               print(f"<<< ✅ Result: {result.content[0].text}")


       if __name__ == "__main__":
           asyncio.run(test_server())

3. In a new terminal, run the test server:

       uv run test_server.py

   You should see the following output:

        🛠️ Tool found: add
        🛠️ Tool found: subtract
        🪛 Calling add tool for 1 + 2
        ✅ Result: 3
        🪛 Calling subtract tool for 10 - 3
        ✅ Result: 7

> [!TIP]
> **Success:** You successfully deployed a remote MCP server to Cloud Run and tested it using the FastMCP client.

## Clean up

To avoid additional charges to your Google Cloud account, delete all the resources
you deployed with this tutorial.

### Delete the project

If you created a new project for this tutorial, delete the project.
If you used an existing project and need to keep it without the changes you added
in this tutorial, [delete resources that you created for the tutorial](https://docs.cloud.google.com/run/docs/tutorials/deploy-remote-mcp-server#delete-resources).


The easiest way to eliminate billing is to delete the project that you
created for the tutorial.

To delete the project:

> [!CAUTION]
> **Caution** : Deleting a project has the following effects:
>
> - **Everything in the project is deleted.** If you used an existing project for the tasks in this document, when you delete it, you also delete any other work you've done in the project.
> - **Custom project IDs are lost.** When you created this project, you might have created a custom project ID that you want to use in the future. To preserve the URLs that use the project ID, such as an `appspot.com` URL, delete selected resources inside the project instead of deleting the whole project.
>
>
> If you plan to explore multiple architectures, tutorials, or quickstarts, reusing projects
> can help you avoid exceeding project quota limits.

1. In the Google Cloud console, go to the **Manage resources** page.

   [Go to Manage resources](https://console.cloud.google.com/iam-admin/projects)
2. In the project list, select the project that you want to delete, and then click **Delete**.
3. In the dialog, type the project ID, and then click **Shut down** to delete the project.

<br />

<br />

### Delete tutorial resources

1. Delete the Cloud Run service you deployed in this tutorial.
   Cloud Run services don't incur costs until they receive requests.

   To delete your Cloud Run service, run the following command:

   ```bash
   gcloud run services delete SERVICE-NAME
   ```

   Replace <var translate="no">SERVICE-NAME</var> with the name of your service.

   You can also delete Cloud Run services from the
   [Google Cloud console](https://console.cloud.google.com/run).
2. Remove the `gcloud` default region configuration you added during tutorial
   setup:

        gcloud config unset run/region

3. Remove the project configuration:

        gcloud config unset project
