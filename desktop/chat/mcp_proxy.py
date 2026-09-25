#!/usr/bin/env python3
"""Stdio MCP server for agents that take MCP servers as commands (Codex): relays every
JSON-RPC message to the demo's streamable-HTTP MCP endpoint. The URL and bearer token come
from the environment (VERTICALS_MCP_URL, VERTICALS_MCP_TOKEN), never from arguments."""
import json
import os
import sys
import urllib.error
import urllib.request

URL = os.environ["VERTICALS_MCP_URL"]
TOKEN = os.environ["VERTICALS_MCP_TOKEN"]
session_id = None


def emit(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def relay(message):
    global session_id
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
               "Authorization": f"Bearer {TOKEN}"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    req = urllib.request.Request(URL, data=json.dumps(message).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=600) as resp:
        session_id = resp.headers.get("Mcp-Session-Id") or session_id
        if resp.status == 202:
            return
        body = resp.read().decode("utf-8", "replace")
        if "text/event-stream" in (resp.headers.get("Content-Type") or ""):
            # One JSON-RPC message per SSE `data:` block.
            for block in body.split("\n\n"):
                data = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
                if data:
                    emit(json.loads(data))
        elif body.strip():
            emit(json.loads(body))


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        message = json.loads(line)
    except ValueError:
        continue
    try:
        relay(message)
    except (OSError, urllib.error.HTTPError, ValueError) as e:
        if isinstance(message, dict) and "id" in message and "method" in message:
            emit({"jsonrpc": "2.0", "id": message["id"],
                  "error": {"code": -32000, "message": f"Verticals MCP unavailable: {e}"}})
