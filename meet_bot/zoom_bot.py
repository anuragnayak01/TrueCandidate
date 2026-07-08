"""
zoom_bot.py — Zoom Observer Bot (Free Developer Account only)

Uses Playwright to join a Zoom meeting via the Zoom Web Client (no SDK needed).
Observes the participant panel for join/leave/speaking events.

NO PAID SUBSCRIPTION REQUIRED.
You only need a free Zoom account + free developer app for webhooks.

Usage:
  python zoom_bot.py \\
    --url "https://zoom.us/j/1234567890?pwd=..." \\
    --meeting-id "meet-001" \\
    --candidate-name "Sarah Chen" \\
    --sherlock "http://localhost:8765"
"""

from __future__ import annotations

import argparse
import asyncio
import time
from typing import Dict, Set, Optional

import httpx
from playwright.async_api import async_playwright, Page


# Zoom Web Client DOM selectors
SEL_JOIN_FROM_BROWSER = 'a:has-text("join from your browser"), a:has-text("Join from Browser")'
SEL_NAME_INPUT        = '#inputname, input[placeholder*="name"]'
SEL_JOIN_BTN          = '#joinBtn, button:has-text("Join"), button[type="submit"]'
SEL_PARTICIPANT_ITEM  = '.participants-item, .participants-list-item__avatar-name, [class*="participant-item"]'
SEL_SPEAKING_ACTIVE   = '[class*="speaking"], [aria-label*="speaking"], [class*="active-speaker"]'
SEL_OPEN_PARTICIPANTS = '[aria-label*="Participants"], [title*="Participants"]'


class ZoomBot:
    """
    Headless bot that joins Zoom via web client and reports
    participant events to Sherlock — no Zoom SDK subscription needed.
    """

    def __init__(
        self,
        meeting_url: str,
        meeting_id: str,
        sherlock_url: str,
        bot_display_name: str = "Sherlock-Bot",
        candidate_name: str = "",
        candidate_email: str = "",
        interviewers: list[str] | None = None,
        headless: bool = False,
    ):
        self.meeting_url      = meeting_url
        self.meeting_id       = meeting_id
        self.sherlock_url     = sherlock_url.rstrip("/")
        self.bot_display_name = bot_display_name
        self.candidate_name   = candidate_name
        self.candidate_email  = candidate_email
        self.interviewers     = interviewers or []
        self.headless         = headless

        self.known_participants: Dict[str, str] = {}
        self.speaking_pids: Set[str]            = set()
        self.http: Optional[httpx.AsyncClient]  = None
        self._session_created = False

    async def run(self):
        self.http = httpx.AsyncClient(timeout=10)
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=self.headless,
                    args=[
                        "--use-fake-ui-for-media-stream",
                        "--use-fake-device-for-media-stream",
                        "--no-sandbox",
                    ],
                )
                context = await browser.new_context(
                    permissions=["camera", "microphone"],
                )
                page = await context.new_page()
                await self._join_meeting(page)
                await self._observe_loop(page)
                await browser.close()
        finally:
            await self.http.aclose()

    async def _join_meeting(self, page: Page):
        await page.goto(self.meeting_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # Try "join from browser" link (avoids app download prompt)
        try:
            link = page.locator(SEL_JOIN_FROM_BROWSER).first
            if await link.is_visible(timeout=5000):
                await link.click()
                await asyncio.sleep(2)
        except Exception:
            pass

        # Enter display name
        try:
            name_input = page.locator(SEL_NAME_INPUT).first
            await name_input.wait_for(state="visible", timeout=10000)
            await name_input.fill(self.bot_display_name)
        except Exception:
            pass

        # Click join
        try:
            btn = page.locator(SEL_JOIN_BTN).first
            await btn.wait_for(state="visible", timeout=10000)
            await btn.click()
            print("[ZoomBot] Clicked Join")
        except Exception as e:
            print(f"[ZoomBot] Join failed: {e}")

        await asyncio.sleep(5)

        # Open participants panel
        try:
            p_btn = page.locator(SEL_OPEN_PARTICIPANTS).first
            if await p_btn.is_visible(timeout=5000):
                await p_btn.click()
                await asyncio.sleep(1)
        except Exception:
            pass

    async def _observe_loop(self, page: Page):
        consecutive_errors = 0
        while True:
            try:
                await self._check_participants(page)
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                print(f"[ZoomBot] Error #{consecutive_errors}: {e}")
                if consecutive_errors > 30:
                    print("[ZoomBot] Too many errors — ending.")
                    break
            await asyncio.sleep(1)

    async def _check_participants(self, page: Page):
        items = await page.query_selector_all(SEL_PARTICIPANT_ITEM)
        current_pids: Set[str] = set()

        for item in items:
            name = (await item.inner_text()).strip().split("\n")[0]
            if not name or name == self.bot_display_name:
                continue

            pid = f"zoom-{abs(hash(name)) % 99999}"
            current_pids.add(pid)

            if pid not in self.known_participants:
                self.known_participants[pid] = name
                print(f"[ZoomBot] JOIN: {name}")
                await self._ensure_session()
                await self._send_event("participant_join", pid, {"display_name": name})

            # Speaking detection
            speaking = await item.query_selector(SEL_SPEAKING_ACTIVE)
            is_speaking = speaking is not None

            if is_speaking and pid not in self.speaking_pids:
                self.speaking_pids.add(pid)
                await self._send_event("speaking_start", pid)
            elif not is_speaking and pid in self.speaking_pids:
                self.speaking_pids.discard(pid)
                await self._send_event("speaking_end", pid)

        for pid in list(self.known_participants.keys()):
            if pid not in current_pids:
                name = self.known_participants.pop(pid)
                self.speaking_pids.discard(pid)
                print(f"[ZoomBot] LEAVE: {name}")
                await self._send_event("participant_leave", pid)

    async def _ensure_session(self):
        if self._session_created:
            return
        try:
            r = await self.http.post(
                f"{self.sherlock_url}/api/meeting/start",
                json={
                    "context": {
                        "meeting_id": self.meeting_id,
                        "candidate_name":  self.candidate_name,
                        "candidate_email": self.candidate_email,
                        "interviewer_names":  self.interviewers,
                        "interviewer_emails": [],
                    }
                },
            )
            if r.status_code == 200:
                self._session_created = True
                print(f"[ZoomBot] Sherlock session ready")
        except Exception as e:
            print(f"[ZoomBot] Session create failed: {e}")

    async def _send_event(self, event_type: str, pid: str, data: dict | None = None):
        try:
            await self.http.post(
                f"{self.sherlock_url}/api/event/{self.meeting_id}",
                json={"event_type": event_type, "participant_id": pid,
                      "timestamp": time.time(), "data": data or {}},
            )
        except Exception as e:
            print(f"[ZoomBot] Send failed: {e}")


async def _main():
    parser = argparse.ArgumentParser(description="Sherlock Zoom Observer Bot")
    parser.add_argument("--url",             required=True)
    parser.add_argument("--meeting-id",      required=True)
    parser.add_argument("--candidate-name",  default="")
    parser.add_argument("--candidate-email", default="")
    parser.add_argument("--interviewers",    default="")
    parser.add_argument("--sherlock",        default="http://localhost:8765")
    parser.add_argument("--bot-name",        default="Sherlock-Bot")
    parser.add_argument("--headless",        action="store_true")
    args = parser.parse_args()

    bot = ZoomBot(
        meeting_url      = args.url,
        meeting_id       = args.meeting_id,
        sherlock_url     = args.sherlock,
        bot_display_name = args.bot_name,
        candidate_name   = args.candidate_name,
        candidate_email  = args.candidate_email,
        interviewers     = [x.strip() for x in args.interviewers.split(",") if x.strip()],
        headless         = args.headless,
    )
    await bot.run()


if __name__ == "__main__":
    asyncio.run(_main())
