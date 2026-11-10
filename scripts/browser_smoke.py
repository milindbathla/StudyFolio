"""Verify the built application in Chromium using a throwaway local profile and SQLite database."""

import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def server(port, folder, vectors=False):
    env = os.environ | {
        "APP_DATA_DIR": str(folder),
        "DATABASE_URL": "sqlite:///" + (folder / "qa.db").as_posix(),
        "CHROMA_PERSIST_DIR": str(folder / "chroma"),
        "LLM_ENABLED": "false",
        "VECTOR_ENABLED": "true" if vectors else "false",
        "NEO4J_PASSWORD": "",
        "APP_PORT": str(port),
        "APP_HOST": "127.0.0.1",
    }
    base = f"http://127.0.0.1:{port}"
    with (folder / "server.log").open("a", encoding="utf8") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "app.cli", "serve"],
            cwd=ROOT / "backend",
            env=env,
            stdout=log,
            stderr=log,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            for _ in range(150):
                if process.poll() is not None:
                    raise RuntimeError(
                        "QA server stopped: "
                        + (folder / "server.log").read_text()[-500:]
                    )
                try:
                    with urlopen(base + "/api/v1/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.2)
            else:
                raise RuntimeError("QA server startup timed out")
            yield base
        finally:
            process.terminate()
            process.wait(timeout=15)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(exist_ok=True, parents=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with (
        tempfile.TemporaryDirectory(prefix="studyfolio-qa-") as directory,
        sync_playwright() as playwright,
    ):
        folder = Path(directory)
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        with server(port, folder) as base:
            page.goto(base)
            expect(
                page.get_by_role("heading", name="What are we studying today?")
            ).to_be_visible()
            if args.screenshots:
                page.screenshot(
                    path=args.screenshots / "chat-desktop.png", full_page=True
                )
            page.get_by_role("button", name="New conversation").click()
            page.wait_for_url("**/chat/*")
            thread_url = page.url
            for message in [
                "I prefer detailed explanations.",
                "My physics quiz is on November 19, 2030.",
            ]:
                page.get_by_label("Your message").fill(message)
                page.get_by_role("button", name="Send message").click()
                expect(
                    page.locator("article.message.user p").filter(has_text=message)
                ).to_be_visible()
            page.get_by_role("link", name="Local Calendar", exact=True).click()
            page.get_by_role("button", name="Confirm", exact=True).click()
            expect(
                page.get_by_role("status").filter(has_text="Event confirmed.")
            ).to_be_visible()
            page.goto(thread_url)
            correction = (
                "Actually, the physics quiz has been moved to November 20, 2030."
            )
            page.get_by_label("Your message").fill(correction)
            page.get_by_role("button", name="Send message").click()
            expect(
                page.locator("article.message.user p").filter(has_text=correction)
            ).to_be_visible()
            page.get_by_role("link", name="Local Calendar", exact=True).click()
            page.get_by_role("button", name="Confirm", exact=True).click()
            page.get_by_role("button", name="Agenda", exact=True).click()
            row = page.get_by_role("button", name="Physics quiz", exact=False)
            expect(row).to_have_count(1)
            expect(row).to_contain_text("2030-11-20")
            row.click()
            page.get_by_role("button", name="Edit", exact=True).click()
            page.get_by_label("Date", exact=True).fill("2030-11-21")
            page.get_by_role("button", name="Save event").click()
            expect(
                page.get_by_role("dialog").get_by_text("2030-11-21 · All day")
            ).to_be_visible()
            page.get_by_role("button", name="Close dialog").click()
            page.get_by_role("link", name="Learner Persona", exact=True).click()
            expect(
                page.get_by_role("heading", name="detailed explanations", exact=True)
            ).to_be_visible()
            page.get_by_role("button", name="Edit", exact=True).click()
            editor = page.get_by_role("dialog", name="Edit memory")
            expect(editor).to_be_visible()
            editor.get_by_role("textbox").fill("worked examples")
            page.get_by_role("button", name="Save correction").click()
            expect(
                page.get_by_role("heading", name="worked examples", exact=True)
            ).to_be_visible()
            page.get_by_role("button", name="History", exact=True).click()
            expect(page.get_by_text("manual edit", exact=False)).to_be_visible()
            page.get_by_role("link", name="Memory Explorer", exact=True).click()
            page.get_by_role("button", name="Semantic memory", exact=True).click()
            expect(
                page.get_by_role("heading", name="explanation depth: worked examples")
            ).to_be_visible()
            current = page.locator("article").filter(
                has=page.get_by_role(
                    "heading", name="explanation depth: worked examples"
                )
            )
            current.get_by_role("link", name="Source", exact=False).click()
            source = page.locator('article.message[data-source="selected"]')
            expect(source).to_contain_text("worked examples")
            assert page.url.endswith("#" + source.get_attribute("id"))
            page.get_by_role("link", name="Settings", exact=True).click()
            page.get_by_label("Recent message limit").fill("19")
            page.get_by_role("button", name="Save preferences").click()
            expect(page.get_by_text("Preferences saved.")).to_be_visible()
        with server(port, folder) as base:
            page.goto(thread_url)
            expect(
                page.locator("article.message.user p").filter(
                    has_text="I prefer detailed explanations."
                )
            ).to_be_visible()
            page.goto(base + "/persona")
            expect(
                page.get_by_role("heading", name="worked examples", exact=True)
            ).to_be_visible()
            page.goto(base + "/calendar")
            page.get_by_role("button", name="Agenda", exact=True).click()
            expect(
                page.get_by_role("button", name="Physics quiz", exact=False)
            ).to_contain_text("2030-11-21")
            page.set_viewport_size({"width": 390, "height": 844})
            page.goto(base + "/chat")
            expect(page.get_by_role("button", name="Open navigation")).to_be_visible()
            page.get_by_role("button", name="Open navigation").click()
            expect(page.get_by_role("link", name="Learner Persona")).to_be_visible()
            page.get_by_role("button", name="Close navigation").click(
                position={"x": 365, "y": 75}
            )
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            if args.screenshots:
                page.screenshot(
                    path=args.screenshots / "chat-mobile.png", full_page=True
                )
        browser.close()
        assert not errors, errors
        print(
            "Chromium verified chat, source-backed persona, memory, calendar confirmation/edit, settings, persistence after process restart, and mobile navigation."
        )


if __name__ == "__main__":
    main()
