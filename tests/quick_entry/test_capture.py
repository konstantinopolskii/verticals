import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('quick_entry', Path(__file__).parents[2] / 'desktop/chat/quick_entry.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Chat:
    def __init__(self): self.created=[]; self.sent=[]
    def api(self, method, path, body, **options):
        self.created.append((method,path,body,options)); return {'id':'SAMPLE01'}
    def send(self, *args): self.sent.append(args)

class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.chat=Chat(); self.q=m.QuickEntry(self.tmp.name,self.chat)
    def test_imperative_is_saved_not_sent_and_retry_survives_restart(self):
        body={'request':'capture-1','action':'inbox','text':'  Сделай отчёт  '}
        result=self.q.capture(body)
        again=m.QuickEntry(self.tmp.name,self.chat).capture(body)
        self.assertEqual(result,again)
        self.assertEqual(len(self.chat.created),1)
        self.assertEqual(self.chat.created[0][2]['title'],'Сделай отчёт')
        self.assertEqual(self.chat.sent,[])
        self.assertEqual(self.chat.created[0][3]['idempotency_key'],'quick-entry-capture-1')
    def test_agent_creates_goal_and_starts_linked_session(self):
        settings={'provider':'codex','permission':'read-only'}
        result=self.q.capture({'request':'agent-1','action':'agent','text':'Hello','settings':settings})
        self.assertTrue(result['session'])
        self.assertEqual(self.chat.sent[0][0],result['session'])
        self.assertEqual(self.chat.sent[0][3],settings)
        self.assertEqual(result['goal'],'SAMPLE01')
        self.assertEqual(len(self.chat.created),1)
        self.assertEqual(self.chat.sent[0][2]['goal'],{'id':'SAMPLE01','title':'Hello'})
        entries=m.QuickEntry(self.tmp.name,self.chat).conversations()
        self.assertEqual(entries[0]['id'],result['session'])
        self.assertEqual(entries[0]['selection'],settings)
    def test_agent_failure_keeps_created_goal_and_retry_does_not_duplicate(self):
        body={'request':'retry-agent','action':'agent','text':'Hello'}
        def fail(*args): raise RuntimeError('Agent unavailable')
        self.chat.send=fail
        first=self.q.capture(body)
        self.assertEqual(first['goal'],'SAMPLE01')
        self.assertIn('Agent unavailable',first['error'])
        self.chat.send=lambda *args: self.chat.sent.append(args)
        result=m.QuickEntry(self.tmp.name,self.chat).capture(body)
        self.assertNotIn('error',result)
        self.assertEqual(result['goal'],first['goal'])
        self.assertEqual(len(self.chat.created),1)
        self.assertEqual(len(self.chat.sent),1)
        self.assertEqual(self.q.capture(body),result)
        self.assertEqual(len(self.chat.sent),1)

    def test_multiline_capture_keeps_original_text(self):
        self.q.capture({'request':'lines','action':'inbox','text':'First\nSecond'})
        self.assertEqual(self.chat.created[0][2]['body'],'First\nSecond')

    def test_empty_or_unknown_action_does_not_write(self):
        for body in [{'request':'a','action':'inbox','text':'  '},{'request':'b','action':'delete','text':'x'}]:
            with self.assertRaises(ValueError):self.q.capture(body)
        self.assertEqual(self.chat.created,[])
    def test_retry_token_cannot_be_reused_with_different_text(self):
        self.q.capture({'request':'a','action':'inbox','text':'One'})
        with self.assertRaises(ValueError): self.q.capture({'request':'a','action':'inbox','text':'Two'})
    def test_invalid_binding_keeps_current_settings(self):
        m.write(Path(self.tmp.name)/'quick-entry-status.json',{'binding':'fn','registered':True})
        for binding in ['cmd+key:999', 'unsupported', '', 'key:-1']:
            with self.assertRaises(ValueError): self.q.binding(binding)
        self.assertEqual(self.q.binding()['binding'],'fn')
        self.assertFalse((Path(self.tmp.name)/'quick-entry-request.json').exists())
    def test_onboarding_created_once_across_restarts_and_preserves_user_edits(self):
        self.q.onboard()
        m.QuickEntry(self.tmp.name,self.chat).onboard()
        self.assertEqual(len(self.chat.created),1)
        method,path,payload,options=self.chat.created[0]
        self.assertEqual((method,path),('POST','/api/goals'))
        self.assertIn('⌘⇧',payload['body'])
        self.assertIn('Accessibility',payload['body'])
        self.assertIn('agent',payload['body'])
        self.assertEqual(options['idempotency_key'],'quick-entry-onboarding-v1')
        self.assertNotIn('vertical',payload)
    def test_startup_never_prompts_for_accessibility(self):
        # A startup must not call the prompting API, even when a build's identity changes.
        native=(Path(__file__).parents[2]/'desktop/macos/QuickEntry.swift').read_text()
        self.assertNotIn('AXIsProcessTrustedWithOptions',native)
    def test_long_text_keeps_full_body(self):
        words='Длинная мысль '*40
        self.q.capture({'request':'long','action':'inbox','text':words})
        body=self.chat.created[0][2]
        self.assertLessEqual(len(body['title']),250)
        self.assertEqual(body['body'],words.strip())

if __name__=='__main__':unittest.main()
