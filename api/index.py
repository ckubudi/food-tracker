"""Entry point Vercel — exporta o ASGI app do MCP server.

Vercel detecta `app` ASGI e serve com Python runtime.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.mcp_server import app  # noqa: E402, F401
