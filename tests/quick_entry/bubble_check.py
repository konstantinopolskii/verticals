"""Run against the isolated app; bridge is recorded, live native/API tested separately."""
from pathlib import Path
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.webkit.launch()
    page=browser.new_page(viewport={"width":600,"height":320})
    page.add_init_script("window.messages=[];window.webkit={messageHandlers:{quickEntry:{postMessage:m=>window.messages.push(m)}}}")
    page.goto('http://127.0.0.1:8388/quick-entry.html')
    field=page.get_by_role('textbox',name='Quick Entry')
    assert field.get_attribute('placeholder')=='Write a thought'
    assert page.locator('html').get_attribute('lang')=='en'
    field.fill('Заметка')
    field.press('Enter')
    assert page.evaluate("messages.filter(m=>m.action==='inbox').length")==1
    assert page.get_by_role('status').inner_text()=='Adding to Inbox…'
    page.evaluate("window.quickEntry.state(false, '')")
    field.fill('Поручение')
    field.press('Meta+Enter')
    assert page.evaluate("messages.filter(m=>m.action==='agent').length")==1
    page.evaluate("window.quickEntry.state(false, 'Не удалось отправить')")
    assert field.input_value()=='Поручение'
    field.press('Shift+Enter')
    assert '\n' in field.input_value()
    field.fill('Длинная мысль ' * 35)
    page.wait_for_timeout(100)
    assert field.evaluate('(e)=>e.clientHeight')>36
    assert page.locator('button').count()==0
    assert field.evaluate("(e)=>getComputedStyle(e).fontSize")=='28px'
    Path('/tmp/quick-entry-evidence').mkdir(exist_ok=True)
    page.screenshot(path='/tmp/quick-entry-evidence/bubble-long.png')
    page.evaluate("window.quickEntry.state(false, '')")
    field.fill('Записать мысль')
    page.screenshot(path='/tmp/quick-entry-evidence/bubble.png')
    field.press('Escape')
    assert page.evaluate("messages.some(m=>m.action==='cancel')")
    browser.close()
print('Bubble keyboard, wrapping, error retention and no buttons passed')
