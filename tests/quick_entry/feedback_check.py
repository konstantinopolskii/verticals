"""Temporal feedback checks in WebKit against the running isolated app."""
from pathlib import Path
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.webkit.launch()
 page=b.new_page(viewport={'width':600,'height':360})
 page.add_init_script("window.messages=[];window.webkit={messageHandlers:{quickEntry:{postMessage:m=>messages.push(m)}}}")
 page.goto('http://127.0.0.1:8388/quick-entry.html')
 f=page.get_by_role('textbox',name='Quick Entry')
 f.fill('A useful thought')
 before=page.locator('.quick-entry').bounding_box()['height']
 f.press('Enter')
 after=page.locator('.quick-entry').bounding_box()['height']
 assert after==before, f'Sending must not add a strip: {before} -> {after}'
 assert page.get_by_role('status').inner_text()=='Adding to Inbox…'
 assert 'Added to Inbox' not in page.locator('body').inner_text()
 assert page.locator('.circle-field__pivot, .circle-field__line').count()==0,'Feedback must be text only'
 page.evaluate("window.quickEntry.complete('inbox')")
 opacity=page.get_by_role('status').evaluate('(e)=>getComputedStyle(e).opacity')
 assert float(opacity)<1,'Confirmation should appear gradually'
 page.wait_for_timeout(140)
 assert page.get_by_role('status').evaluate('(e)=>getComputedStyle(e).opacity')=='1'

 assert page.get_by_role('status').inner_text()=='Added to Inbox'
 assert page.locator('.quick-entry').bounding_box()['height']==before
 page.screenshot(path='/tmp/quick-entry-evidence/feedback-inbox.png')
 page.evaluate("window.quickEntry.state(false, '', true)")
 f.fill('Ask the agent')
 f.press('Meta+Enter')
 assert page.get_by_role('status').inner_text()=='Starting agent…'
 page.evaluate("window.quickEntry.complete('agent')")
 assert page.get_by_role('status').inner_text()=='Sent to agent'
 page.screenshot(path='/tmp/quick-entry-evidence/feedback-agent.png')
 page.evaluate("window.quickEntry.state(false, 'Could not send. Try again.')")
 assert f.input_value()=='Ask the agent'
 assert f.is_editable()
 page.screenshot(path='/tmp/quick-entry-evidence/feedback-error.png')
 page.emulate_media(reduced_motion='reduce')
 f.press('Enter')
 page.evaluate("window.quickEntry.complete('inbox')")
 assert page.get_by_role('status').evaluate('(e)=>getComputedStyle(e).animationName')=='none'
 assert page.locator('.circle-field__pivot, .circle-field__line').count()==0
 b.close()
print('No strip or resize; text-only progress, success, error retention and reduced motion passed')
