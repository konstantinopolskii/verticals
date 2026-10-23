"""Chats started by Verticals get a place and a name without changing their access."""

import copy
import threading
import types
import uuid

import pytest

from tests.static.sample_sessions import chat_module


@pytest.fixture
def setup(tmp_path, monkeypatch):
    chat = chat_module()
    host = chat.Chat(tmp_path, 'http://127.0.0.1:9/mcp', 'synthetic', watch_every=0)
    state = types.SimpleNamespace(sections=[], threads={}, calls=[], fail=None, pages=None, turn_started=threading.Event())

    class Rpc:
        def __init__(self, argv, cwd, env, *callbacks):
            self.cwd, self.env = cwd, env

        def notify(self, *args):
            pass

        def request(self, method, params, timeout=45):
            state.calls.append((method, copy.deepcopy(params)))
            if method == state.fail:
                raise chat.ChatError('Synthetic unsupported method')
            if method == 'initialize':
                return {}
            if method == 'thread/start':
                key = str(uuid.uuid4())
                state.threads[key] = {'id': key, 'name': None, 'section': None}
                return {'thread': copy.deepcopy(state.threads[key])}
            if method == 'thread/resume':
                return {'thread': copy.deepcopy(state.threads[params['threadId']])}
            if method == 'threadSection/list':
                if state.pages:
                    return state.pages[params.get('cursor')]
                return {'data': copy.deepcopy(state.sections), 'nextCursor': None}
            if method == 'threadSection/create':
                section = {'id': str(uuid.uuid4()), 'name': params['name']}
                state.sections.append(section)
                return {'section': section}
            if method == 'thread/section/move':
                state.threads[params['threadId']]['section'] = next(
                    s for s in state.sections if s['id'] == params['sectionId'])
                return {}
            if method == 'thread/name/set':
                state.threads[params['threadId']]['name'] = params['name']
                return {}
            if method == 'turn/start':
                state.turn_started.set()
                return {'turn': {'id': 'synthetic-turn'}}
            raise AssertionError(method)

    monkeypatch.setattr(chat, 'RpcProcess', Rpc)
    monkeypatch.setattr(chat, 'codex_args', lambda *args, **kwargs: ['codex', 'app-server'])

    def start(entry=None, thread=None, settings=None, key=None, quiet=False):
        key = key or str(uuid.uuid4())
        if entry is not None:
            host.update(key, **entry)
        if thread:
            state.threads[thread['id']] = copy.deepcopy(thread)
        raw = settings or {}
        settings = chat.clean_settings({'provider': 'codex', **raw})
        if 'role' in raw:
            settings['role'] = raw['role']
        events = []
        session = types.SimpleNamespace(settings=settings, emit=events.append)
        if not quiet:
            session.id = key
        agent = chat.CodexAgent(host, session, settings, thread['id'] if thread else None)
        return agent, key, events

    yield host, state, start
    host.shutdown()


def test_new_task_chat_gets_its_task_title_and_a_section_without_changing_access(setup):
    host, state, start = setup
    agent, key, _ = start({'goal': {'id': 'SYN00001', 'title': 'Plan the launch'}},
                          settings={'permission': 'full-access'})
    thread = state.threads[agent.thread_id]
    assert thread['name'] == 'Plan the launch'
    assert thread['section']['name'] == 'Verticals'
    assert agent.proc.cwd == host.workdir
    params = next(p for m, p in state.calls if m == 'thread/start')
    assert params['sandbox'] == 'danger-full-access'


def test_free_chat_uses_the_first_user_message_not_app_context(setup):
    _, state, start = setup
    agent, _, _ = start({'transcript': [['user', '  Review\n  this plan  '], ['assistant', 'Done'], ['user', 'Continue']]})
    assert state.threads[agent.thread_id]['name'] == 'Review this plan'


def test_long_chat_titles_stay_readable(setup):
    _, state, start = setup
    agent, _, _ = start({'goal': {'title': 'A' * 400}})
    title = state.threads[agent.thread_id]['name']
    assert title.startswith('A' * 50) and len(title) <= 120


def test_resume_leaves_older_chats_placement_and_name_to_the_owner(setup):
    _, state, start = setup
    agent, _, _ = start({'goal': {'title': 'Continue the plan'}},
                        thread={'id': 'existing-thread', 'name': None, 'section': None})
    assert agent.thread_id == 'existing-thread'
    assert state.threads[agent.thread_id]['name'] is None
    assert state.threads[agent.thread_id]['section'] is None
    assert not any(m == 'thread/start' for m, _ in state.calls)


def test_manual_title_and_section_are_preserved(setup):
    _, state, start = setup
    thread = {'id': 'manual', 'name': 'My chosen name', 'section': {'id': 'chosen', 'name': 'My work'}}
    start({'goal': {'title': 'Task title'}}, thread=thread)
    assert state.threads['manual'] == thread
    assert not any(m in {'thread/name/set', 'thread/section/move', 'threadSection/create'} for m, _ in state.calls)


def test_owner_can_remove_an_already_organized_chat_from_its_section(setup):
    _, state, start = setup
    agent, key, _ = start({'goal': {'title': 'Plan'}})
    thread = {'id': agent.thread_id, 'name': 'Renamed outside', 'section': None}
    state.calls.clear()
    start(thread=thread, key=key)
    assert state.threads[thread['id']] == thread
    assert not any(m.startswith('threadSection/') or m == 'thread/section/move' for m, _ in state.calls)


def test_existing_section_is_reused_even_when_it_is_on_a_later_page(setup):
    _, state, start = setup
    section = {'id': 'verticals', 'name': 'Verticals'}
    state.sections = [section]
    state.pages = {None: {'data': [{'id': 'other', 'name': 'Other'}], 'nextCursor': 'next'},
                   'next': {'data': [section], 'nextCursor': None}}
    a, _, _ = start()
    b, _, _ = start()
    assert state.threads[a.thread_id]['section'] == state.threads[b.thread_id]['section'] == section
    assert not any(m == 'threadSection/create' for m, _ in state.calls)


def test_external_linked_codex_chat_keeps_its_name_and_place(setup):
    _, state, start = setup
    thread = {'id': 'outside', 'name': None, 'section': None}
    start({'external': True, 'goal': {'title': 'Linked task'}}, thread=thread)
    assert state.threads['outside'] == thread
    assert not any(m in {'thread/name/set', 'thread/section/move', 'threadSection/create'} for m, _ in state.calls)


def test_report_checker_is_grouped_and_named_too(setup):
    _, state, start = setup
    agent, _, _ = start(settings={'role': 'checker', 'sources': 'connected'}, quiet=True)
    thread = state.threads[agent.thread_id]
    assert thread['section']['name'] == 'Verticals'
    assert thread['name'] == 'Morning report check'


@pytest.mark.parametrize('method', ['thread/name/set', 'threadSection/list', 'threadSection/create', 'thread/section/move'])
def test_old_or_unavailable_sidebar_api_does_not_block_the_agent(setup, method):
    host, state, start = setup
    state.fail = method
    agent, key, events = start()
    assert any(e['t'] == 'ready' for e in events)
    agent.send('Continue safely')
    assert state.turn_started.wait(timeout=1)
    assert any(m == 'turn/start' for m, _ in state.calls)
    assert host.load().get(key, {}).get('codex_sidebar_thread') is None
