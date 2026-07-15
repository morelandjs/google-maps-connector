import os
import sys
from pathlib import Path

# Make the flat-layout source files importable from tests/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env if it exists so live smoke tests see the real key. setdefault below
# only kicks in if .env didn't supply one, keeping hermetic tests working.
try:
    from dotenv import load_dotenv

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

# server.py raises at import time if this is missing; mocked tests don't need
# a real key. Guard against empty values too — a blank `GOOGLE_MAPS_API_KEY=`
# line in .env makes load_dotenv set the var to "" (which setdefault won't fix).
if not os.environ.get("GOOGLE_MAPS_API_KEY"):
    os.environ["GOOGLE_MAPS_API_KEY"] = "TEST_KEY"
if not os.environ.get("GEMINI_API_KEY"):
    os.environ["GEMINI_API_KEY"] = "TEST_GEMINI_KEY"

# Tests run unauthenticated so the in-process MCP Client doesn't have to
# complete an OAuth dance for every call. The Phase 2 exit criterion (server
# rejects unauth'd, accepts authenticated) is verified manually with MCP
# Inspector — see INSTRUCTIONS.md.
for _oauth_var in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"):
    os.environ.pop(_oauth_var, None)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_area_viewport_cache():
    """The area→viewport cache is module-level state; isolate tests from it."""
    import server

    server._AREA_VIEWPORT_CACHE.clear()
    yield
