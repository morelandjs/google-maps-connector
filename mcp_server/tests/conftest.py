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
# a real key.
os.environ.setdefault("GOOGLE_MAPS_API_KEY", "TEST_KEY")

# Tests run unauthenticated so the in-process MCP Client doesn't have to
# complete an OAuth dance for every call. The Phase 2 exit criterion (server
# rejects unauth'd, accepts authenticated) is verified manually with MCP
# Inspector — see INSTRUCTIONS.md.
for _oauth_var in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"):
    os.environ.pop(_oauth_var, None)
