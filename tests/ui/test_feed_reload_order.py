"""A reload from the change feed never puts back a state the board has already left."""
from playwright.sync_api import expect

from tests.ui.conftest import UiSession


def test_a_goal_ticked_and_unticked_fast_never_steps_back(ui_f2: UiSession):
    page = ui_f2.page
    page.wait_for_selector('.goal-card__row')
    rows = '[data-vertical="month"] [data-section="planned"] > .goal-card'
    first = page.locator(rows).first
    goal = first.get_attribute('data-goal-id')
    box = page.locator(f'{rows}[data-goal-id="{goal}"] [data-cap="complete"]').first
    page.evaluate('''([rows, goal]) => {
        window.__states = []
        const read = () => {
            const cards = [...document.querySelectorAll(rows)]
            const card = cards.find((c) => c.dataset.goalId === goal)
            if (!card) return
            const state = `${cards.indexOf(card)}:${card.querySelector('[data-cap=complete]').getAttribute('aria-checked')}`
            if (window.__states.at(-1) !== state) window.__states.push(state)
        }
        read()
        new MutationObserver(read).observe(document.body, { subtree: true, childList: true, attributes: true })
    }''', [rows, goal])

    # A hosted server answers in about 0.3 s, and the feed rings after each write: the board read after the first tick
    # arrives after the second. A local server answers too fast to show it, so the board's answer is held back.
    def slow(route):
        answer = route.fetch()
        page.wait_for_timeout(700)
        route.fulfill(response=answer)

    page.route('**/api/board?*', slow)
    box.click()
    expect(box).to_have_attribute('aria-checked', 'true')
    page.wait_for_timeout(450)
    page.locator(f'{rows}[data-goal-id="{goal}"] [data-cap="complete"]').first.click()
    page.wait_for_timeout(2500)  # the feed's reloads land meanwhile
    states = page.evaluate('window.__states')
    done = [state.endswith('true') for state in states]
    flips = sum(1 for a, b in zip(done, done[1:]) if a != b)
    assert flips == 2, states  # one change each way, and nothing comes back
