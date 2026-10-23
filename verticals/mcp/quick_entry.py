"""The native Quick Entry binding, changed only through the agent."""
import json
import urllib.request
from mcp import types
from verticals.mcp.shapes import ok, error_result

TOOLS = (types.Tool(name='quick_entry_binding', description=(
    'Read or change the global Quick Entry key of the desktop app. Omit binding to read. '
    'Default is cmd+shift+key:49 (Command+Shift+Space), without Accessibility permission. Modifier-only shortcuts such as fn require Accessibility. For a key use macOS virtual key code: key:49 is Space; '
    'prefix modifiers ctrl+, alt+, shift+, cmd+ as needed. No settings UI. '
    'A native registration result is not proof that another app will not also act: test a real key press. '
    'On a registration failure the previous binding stays active.'), input_schema={
        'type':'object','properties':{'binding':{'type':'string'},'client_token':{'type':'string'}},
        'additionalProperties':False}),)


def handle(conn, owner, args, gateway_url):
    if not gateway_url: return error_result('Quick Entry needs the desktop app')
    request=urllib.request.Request(gateway_url.rstrip('/')+'/__chat/quick-entry-binding',
        data=json.dumps({'binding':args['binding']}).encode() if 'binding' in args else None,
        headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=6) as response: result=json.load(response)
        return ok('Quick Entry binding',result)
    except (OSError,ValueError) as exc:
        return error_result('Could not read/apply Quick Entry binding: '+str(exc))
