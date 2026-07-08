"""
gmeet_bot.py — Google Meet Observer Bot (No API, No Subscription)

Uses Playwright to join a Google Meet as a "silent observer" bot.
Watches the DOM for participant join/leave/speaking events and forwards
them to the Sherlock engine via HTTP.

Requirements:
  pip install playwright httpx
  playwright install chromium

Usage:
  python gmeet_bot.py \\
    --url "https://meet.google.com/abc-defg-hij" \\
    --meeting-id "meet-001" \\
    --candidate-name "Sarah Chen" \\
    --candidate-email "sarah.chen@gmail.com" \\
    --interviewers "Alex Rivera,Jordan Kim" \\
    --sherlock "http://localhost:8765"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import re
from typing import Dict, Optional, Set

import httpx
from playwright.async_api import async_playwright, Page, Browser


# ---------------------------------------------------------------------------
# Google Meet DOM selectors (as of 2025 — may need updating if Meet changes)
# ---------------------------------------------------------------------------

# Participant list panel items
SEL_PARTICIPANT_CHIP   = '[data-participant-id]'
SEL_PARTICIPANT_NAME   = '[data-self-name], .zWGUib, [jsname="V68bde"]'
SEL_SPEAKING_INDICATOR = '[data-is-speaking="true"], .ZwUO9, [aria-label*="speaking"]'

# Pre-join / in-meeting selectors
SEL_JOIN_BTN    = 'button:has-text("Join now"), button:has-text("Ask to join"), [data-idom-class="join-button"]'
SEL_MIC_BTN     = '[data-tooltip*="microphone"], [aria-label*="microphone"]'
SEL_CAM_BTN     = '[data-tooltip*="camera"], [aria-label*="camera"]'

# Caption / transcript elements
SEL_CAPTION     = '[jsname="tgaKEf"], .TBMuR, [data-message-id]'

# Participant panel open button
SEL_PEOPLE_BTN  = '[aria-label*="participant"], [data-tooltip*="participant"]'


class GoogleMeetBot:
    """
    Headless Playwright bot that joins a Google Meet and reports
    participant events to Sherlock without any Google API subscription.
    """

    def __init__(
        self,
        meeting_url: str,
        meeting_id: str,
        sherlock_url: str,
        bot_email: str,
        bot_password: str,
        candidate_name: str = "",
        candidate_email: str = "",
        interviewers: list[str] | None = None,
        headless: bool = False,
    ):
        self.meeting_url   = meeting_url
        self.meeting_id    = meeting_id
        self.sherlock_url  = sherlock_url.rstrip("/")
        self.bot_email     = bot_email
        self.bot_password  = bot_password
        self.candidate_name  = candidate_name
        self.candidate_email = candidate_email
        self.interviewers    = interviewers or []
        self.headless = headless

        self.known_participants: Dict[str, str] = {}   # pid → display_name
        self.speaking_pids: Set[str]            = set()
        self.http: Optional[httpx.AsyncClient]  = None
        self._session_created = False

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    async def run(self):
        self.http = httpx.AsyncClient(timeout=10)
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=self.headless,
                    args=[
                        "--use-fake-ui-for-media-stream",    # auto-allow mic/cam
                        "--use-fake-device-for-media-stream",# use silent mic/cam
                        "--disable-blink-features=AutomationControlled",
                        "--disable-web-security",
                        "--no-sandbox",
                    ],
                )
                context = await browser.new_context(
                    permissions=["camera", "microphone"],
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
                page = await context.new_page()

                print(f"[Bot] Logging into Google as {self.bot_email}...")
                await self._google_login(page)

                print(f"[Bot] Joining meeting: {self.meeting_url}")
                await self._join_meeting(page)

                print("[Bot] Inside meeting — starting observation loop...")
                await self._observe_loop(page)

                await browser.close()
        finally:
            await self.http.aclose()

    # ------------------------------------------------------------------
    # Google login
    # ------------------------------------------------------------------

    async def _google_login(self, page: Page):
        await page.goto("https://accounts.google.com/signin", wait_until="networkidle")
        await asyncio.sleep(1)

        # Email
        await page.fill('input[type="email"]', self.bot_email)
        await page.keyboard.press("Enter")
        await page.wait_for_selector('input[type="password"]', state="visible", timeout=15000)
        await asyncio.sleep(1)

        # Password
        await page.fill('input[type="password"]', self.bot_password)
        await page.keyboard.press("Enter")
        await asyncio.sleep(3)

        print("[Bot] Google login complete.")

    # ------------------------------------------------------------------
    # Join the meeting
    # ------------------------------------------------------------------

    async def _join_meeting(self, page: Page):
        await page.goto(self.meeting_url, wait_until="domcontentloaded")
        await asyncio.sleep(4)

        # Turn off mic + camera before joining (be a silent observer)
        try:
            mic = page.locator(SEL_MIC_BTN).first
            if await mic.is_visible():
                await mic.click()
                print("[Bot] Microphone muted")
        except Exception:
            pass

        try:
            cam = page.locator(SEL_CAM_BTN).first
            if await cam.is_visible():
                await cam.click()
                print("[Bot] Camera off")
        except Exception:
            pass

        # Click Join
        await asyncio.sleep(1)
        try:
            join = page.locator(SEL_JOIN_BTN).first
            await join.wait_for(state="visible", timeout=20000)
            await join.click()
            print("[Bot] Clicked Join button")
        except Exception as e:
            print(f"[Bot] Could not click join button: {e}")

        # Wait to be admitted
        await asyncio.sleep(5)

        # Open participants panel
        try:
            people = page.locator(SEL_PEOPLE_BTN).first
            if await people.is_visible():
                await people.click()
                await asyncio.sleep(1)
                print("[Bot] Opened participants panel")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Main observation loop
    # ------------------------------------------------------------------

    async def _observe_loop(self, page: Page):
        """Poll the DOM every second to detect participant + speaking changes."""
        consecutive_errors = 0

        while True:
            try:
                await self._check_participants(page)
                await self._check_captions(page)
                consecutive_errors = 0
            except Exception as e:
                consecutive_errors += 1
                print(f"[Bot] Observer error #{consecutive_errors}: {e}")
                if consecutive_errors > 30:
                    print("[Bot] Too many errors — meeting may have ended.")
                    break

            await asyncio.sleep(1)

    async def _check_participants(self, page: Page):
        """Detect participant join/leave/speaking changes via DOM."""

        # --- Strategy 1: data-participant-id chips ---
        tiles = await page.query_selector_all(SEL_PARTICIPANT_CHIP)
        current_pids: Set[str] = set()

        for tile in tiles:
            pid = await tile.get_attribute("data-participant-id")
            if not pid:
                continue
            current_pids.add(pid)

            # Extract name
            name = await self._extract_name(tile, pid)

            # New join
            if pid not in self.known_participants:
                self.known_participants[pid] = name
                print(f"[Bot] JOIN: {name} ({pid})")
                await self._send_event("participant_join", pid, {"display_name": name})
                if not self._session_created:
                    await self._ensure_session()

            # Name change
            elif self.known_participants[pid] != name and name != "Unknown":
                old_name = self.known_participants[pid]
                self.known_participants[pid] = name
                print(f"[Bot] RENAME: {old_name} → {name}")
                await self._send_event("name_change", pid, {"new_name": name})

            # Speaking
            speaking = await tile.query_selector(SEL_SPEAKING_INDICATOR)
            is_speaking = speaking is not None

            if is_speaking and pid not in self.speaking_pids:
                self.speaking_pids.add(pid)
                print(f"[Bot] SPEAKING: {name}")
                await self._send_event("speaking_start", pid)

            elif not is_speaking and pid in self.speaking_pids:
                self.speaking_pids.discard(pid)
                await self._send_event("speaking_end", pid)

        # Detect leaves
        for pid in list(self.known_participants.keys()):
            if pid not in current_pids:
                name = self.known_participants.pop(pid)
                self.speaking_pids.discard(pid)
                print(f"[Bot] LEAVE: {name}")
                await self._send_event("participant_leave", pid)

        # --- Strategy 2: Fallback — use visible name labels if no pid chips ---
        if not tiles:
            await self._fallback_name_detection(page)

    async def _extract_name(self, tile, pid: str) -> str:
        """Try multiple selectors to extract participant name."""
        for sel in [
            '[data-self-name]',
            '.zWGUib',
            '[jsname="V68bde"]',
            '[aria-label]',
            'span',
        ]:
            try:
                el = await tile.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip()
                    if text and len(text) > 1 and text.lower() not in ("you",):
                        return text
            except Exception:
                pass
        return self.known_participants.get(pid, f"Participant-{pid[:6]}")

    async def _fallback_name_detection(self, page: Page):
        """
        Fallback: scrape all visible name labels from the video grid.
        Assigns sequential IDs since we have no participant IDs.
        """
        name_labels = await page.query_selector_all('.zWGUib, [jsname="V68bde"]')
        current_names = set()

        for el in name_labels:
            name = (await el.inner_text()).strip()
            if not name:
                continue
            current_names.add(name)

            # Synthesize a stable pid from the name
            pid = f"fb-{abs(hash(name)) % 99999}"
            if pid not in self.known_participants:
                self.known_participants[pid] = name
                await self._send_event("participant_join", pid, {"display_name": name})

        for pid in list(self.known_participants.keys()):
            if pid.startswith("fb-"):
                name = self.known_participants[pid]
                if name not in current_names:
                    self.known_participants.pop(pid)
                    await self._send_event("participant_leave", pid)

    async def _check_captions(self, page: Page):
        """
        If Google Meet captions are on, scrape and forward transcript segments.
        Enable captions in the meeting via More options → Turn on captions.
        """
        try:
            caption_els = await page.query_selector_all(SEL_CAPTION)
            for el in caption_els:
                text = (await el.inner_text()).strip()
                if not text or len(text) < 10:
                    continue

                # Try to find the speaker name (usually in a sibling element)
                parent = await el.evaluate_handle("el => el.closest('[data-message-id]')")
                speaker_el = await parent.query_selector('.NWpY1d, [jsname="r4nke"]') if parent else None
                speaker_name = (await speaker_el.inner_text()).strip() if speaker_el else None

                # Match speaker name to known participant
                pid = self._resolve_pid_by_name(speaker_name) if speaker_name else None
                if pid and text:
                    await self._send_event("transcript_segment", pid, {"text": text})
        except Exception:
            pass

    def _resolve_pid_by_name(self, name: str) -> Optional[str]:
        if not name:
            return None
        for pid, pname in self.known_participants.items():
            if pname.lower() == name.lower():
                return pid
        # Fuzzy: check if name is substring
        for pid, pname in self.known_participants.items():
            if name.lower() in pname.lower() or pname.lower() in name.lower():
                return pid
        return None

    # ------------------------------------------------------------------
    # Sherlock HTTP API
    # ------------------------------------------------------------------

    async def _ensure_session(self):
        """Create a Sherlock session for this meeting if not already done."""
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
                        "company": "Live Meeting",
                    },
                    "events": [],  # No pre-loaded events — real-time from bot
                },
            )
            if r.status_code == 200:
                self._session_created = True
                print(f"[Bot] Sherlock session created: {self.meeting_id}")
        except Exception as e:
            print(f"[Bot] Failed to create Sherlock session: {e}")

    async def _send_event(self, event_type: str, participant_id: str, data: dict | None = None):
        """POST a single event to Sherlock's inject endpoint."""
        if not self._session_created and event_type == "participant_join":
            await self._ensure_session()

        try:
            await self.http.post(
                f"{self.sherlock_url}/api/event/{self.meeting_id}",
                json={
                    "event_type": event_type,
                    "participant_id": participant_id,
                    "timestamp": time.time(),
                    "data": data or {},
                },
            )
        except Exception as e:
            print(f"[Bot] Event send failed ({event_type}): {e}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

async def _main():
    parser = argparse.ArgumentParser(description="Sherlock Google Meet Observer Bot")
    parser.add_argument("--url",             required=True,  help="Google Meet URL")
    parser.add_argument("--meeting-id",      required=True,  help="Sherlock meeting ID")
    parser.add_argument("--bot-email",       required=True,  help="Google account email for bot")
    parser.add_argument("--bot-password",    required=True,  help="Google account password for bot")
    parser.add_argument("--candidate-name",  default="",     help="Candidate name from ATS")
    parser.add_argument("--candidate-email", default="",     help="Candidate email from ATS")
    parser.add_argument("--interviewers",    default="",     help="Comma-separated interviewer names")
    parser.add_argument("--sherlock",        default="http://localhost:8765", help="Sherlock server URL")
    parser.add_argument("--headless",        action="store_true", help="Run browser headless (for servers)")
    args = parser.parse_args()

    bot = GoogleMeetBot(
        meeting_url    = args.url,
        meeting_id     = args.meeting_id,
        sherlock_url   = args.sherlock,
        bot_email      = args.bot_email,
        bot_password   = args.bot_password,
        candidate_name  = args.candidate_name,
        candidate_email = args.candidate_email,
        interviewers    = [x.strip() for x in args.interviewers.split(",") if x.strip()],
        headless        = args.headless,
    )

    await bot.run()


if __name__ == "__main__":
    asyncio.run(_main())
