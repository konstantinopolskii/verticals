"""Run the desktop morning even when WebKit has suspended the window."""
from datetime import datetime
import json
import os
import threading
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class MorningSchedule:
    def __init__(self, chat):
        self.chat = chat
        self.path = chat.state_dir / "morning.json"
        self.lock = threading.Lock()
        self.last_checked = None
        self.now = lambda zone: datetime.now(ZoneInfo(zone))

    def load(self):
        try:
            value = json.loads(self.path.read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, value):
        temporary = self.path.with_suffix(".tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
        os.replace(temporary, self.path)

    def configure(self, settings, timezone):
        from chat import AGENTS, clean_settings
        if not isinstance(settings, dict) or settings.get("provider") not in AGENTS:
            raise ValueError("Choose an installed agent first")
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            raise ValueError("Choose a valid timezone") from None
        with self.lock:
            saved = self.load()
            saved.update(settings=clean_settings(settings), timezone=timezone)
            saved["settings"].pop("sources", None)
            self.save(saved)

    def tick(self):
        from chat import which
        with self.lock:
            if self.chat.stopping.is_set():
                return None
            saved = self.load()
            if not saved.get("settings") or not saved.get("timezone"):
                return None
            now = self.now(saved["timezone"])
            self.last_checked = now.isoformat()
            day = now.date().isoformat()
            if now.hour < 7:
                return None
            run = saved.get("run")
            if run and run["day"] == day and run.get("sent"):
                return run
            if self.chat.busy() or not which(saved["settings"]["provider"]):
                return None
            try:
                if not run or run["day"] != day:
                    begun = self.chat.api("POST", f"/api/morning?date={day}", {})
                    if not begun.get("asked") or not begun.get("task_id"):
                        return None
                    run = {"day": day, "task": begun["task_id"], "session": str(uuid.uuid4()),
                           "settings": {**saved["settings"], "sources": "connected"},
                           "landed": begun.get("landed", []), "sent": False}
                    saved["run"] = run
                    self.save(saved)
                if self.chat.stopping.is_set():
                    return None
                context = {"today": day, "now": now.strftime("%Y-%m-%d %H:%M"), "tz": saved["timezone"],
                           "morning": {"day": day, "task": run["task"]},
                           "goal": {"id": run["task"], "title": "Morning report"}}
                self.chat.send(run["session"], morning_ask(day, run["task"], run["landed"]), context, run["settings"])
                run["sent"] = True
                self.save(saved)
                self.chat.log.info("morning_dispatched day=%s session=%s", day, run["session"][:8])
                return run
            except Exception as error:
                self.chat.log.warning("morning_deferred day=%s error=%s", day, type(error).__name__)
                return None

    def status(self):
        with self.lock:
            saved = self.load()
            return {"configured": bool(saved.get("settings")), "timezone": saved.get("timezone"),
                    "last_checked": self.last_checked}

    def start(self, every=30):
        def watch():
            while not self.chat.stopping.is_set():
                try:
                    self.tick()
                except Exception as error:
                    self.chat.log.warning("morning_timer_failed error=%s", type(error).__name__)
                if self.chat.stopping.wait(every):
                    return
        threading.Thread(target=watch, daemon=True).start()


def morning_ask(day, task, landed):
    months = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
    date = datetime.fromisoformat(day)
    title = f"{date.day} {months[date.month - 1]} {date.year}"
    ask = (f"Make my morning report for {day}, following the morning report guide in your instructions. Save it as the "
           f'document reports/morning/{day}.md titled "Morning report — {title}" and link it to its task, '
           f'"Morning report" (id {task}), which is in Day for today already. Then answer in two short lines and link the document.')
    if landed:
        lines = [f'- {item["title"]} (id {item["goal_id"]}): {json.dumps(item["text"][:400], ensure_ascii=False)}'
                 for item in landed[:30]]
        ask += "\n\nMy comments from the last report are on their tasks already, word for word. Each is cut at 400 characters here, if it is longer:\n" + "\n".join(lines)
    return ask
