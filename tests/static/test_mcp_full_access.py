"""Full access settles tool consent, while actual MCP forms still reach the owner."""
from types import SimpleNamespace
import pytest
from tests.static.test_chat_gateway import _chat


def request(settings, kind='mcp_tool_call', mode='form', tool=None, server='verticals_desktop', reads=None, memory=False):
    module = _chat()
    replies, asks = [], []
    agent = object.__new__(module.CodexAgent)
    agent.settings = settings
    agent.approvals = {}
    agent.pending_mcp = {}
    agent.reads = reads or {}
    agent.chat = SimpleNamespace(memory_write=lambda tool, args: memory)
    agent.thread_id = None
    agent.proc = SimpleNamespace(reply=lambda *a, **kw: replies.append((a,kw)))
    agent.s = SimpleNamespace(ask=lambda *a, **kw: asks.append(a), emit=lambda e: None)
    if tool:
        agent.notify('item/started', {'item': {'id':'call-1','type':'mcpToolCall','server':server,'tool':tool,'arguments':{'id':'SYN00001'}}})
    agent.request({'id':7,'method':'mcpServer/elicitation/request','params':{
        'serverName':server,'mode':mode,
        '_meta':{'codex_approval_kind':kind,'tool_params':{'id':'SYN00001'}},
        'message':'A tool approval' if kind else 'Enter a value',
        'requestedSchema':{'type':'object','properties':{}},
    }})
    return replies, asks


@pytest.mark.parametrize('sources', [None,'connected'])
def test_full_access_accepts_tool_consent_without_waiting_for_the_owner(sources):
    replies, asks = request({'permission':'full-access','sources':sources})
    assert not asks
    assert replies == [((7, {'action':'accept','content':{},'_meta':None}),{})]


@pytest.mark.parametrize('settings,kind,mode', [
    ({'permission':'default'},'mcp_tool_call','form'),
    ({'permission':'full-access','role':'checker'},'mcp_tool_call','form'),
    ({'permission':'full-access'},None,'form'),
    ({'permission':'full-access'},'mcp_tool_call','url'),
])
def test_restricted_tools_and_real_forms_still_require_a_decision(settings,kind,mode):
    replies, asks = request(settings,kind,mode)
    assert not replies
    assert len(asks)==1


@pytest.mark.parametrize('role', [None,'checker'])
def test_morning_seats_read_the_board_without_a_permission_prompt(role):
    replies, asks=request({'sources':'connected','role':role}, tool='doc_get')
    assert replies and not asks


def test_checker_reads_only_the_sources_the_owner_approved():
    replies, asks=request({'sources':'connected','role':'checker'},tool='history',server='approved_chat',reads={'mcp__approved_chat__history':'Team chat'})
    assert replies and not asks
    replies, asks=request({'sources':'connected','role':'checker'},tool='history',server='other_chat')
    assert asks and not replies


def test_checker_does_not_approve_a_write_with_the_same_arguments_as_a_read():
    replies, asks=request({'sources':'connected','role':'checker'},tool='doc_delete')
    assert asks and not replies


@pytest.mark.parametrize('role,memory,tool,answered', [
    (None, True, 'doc_save', True),
    (None, False, 'doc_save', False),
    (None, True, 'doc_delete', False),
    ('checker', True, 'doc_save', False),
])
def test_a_write_to_the_agents_memory_runs_without_a_question(role, memory, tool, answered):
    replies, asks = request({'permission':'default','role':role}, tool=tool, memory=memory)
    assert bool(replies) == answered and bool(asks) != answered
