"""Verify local source upload, field confirmation, evidence-grounded chat, and restart through Chromium."""

import json
import socket
import tempfile
from pathlib import Path

import pymupdf
from browser_smoke import server
from playwright.sync_api import expect, sync_playwright


def document(pages):
    with pymupdf.open() as pdf:
        for lines in pages:
            page = pdf.new_page()
            for i, line in enumerate(lines):
                page.insert_text((40, 45 + 20 * i), line)
        return pdf.tobytes()


def main():
    import argparse
    import time
    parser=argparse.ArgumentParser()
    parser.add_argument("--vectors",action="store_true")
    args=parser.parse_args()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory() as tmp, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        with server(port, Path(tmp),vectors=args.vectors) as base:
            page.goto(base + "/settings")
            page.get_by_role("link", name="Data sources").click()

            def upload(name, data, kind):
                page.get_by_label("Document type", exact=True).select_option(kind)
                page.get_by_label("Academic file").set_input_files(
                    {
                        "name": name,
                        "mimeType": "application/json"
                        if name.endswith(".json")
                        else "application/pdf",
                        "buffer": data,
                    }
                )
                page.get_by_role("button", name="Upload locally").click()
                expect(
                    page.get_by_role("heading", name=name, exact=True)
                ).to_be_visible(timeout=15000)
                expect(page.get_by_text("ready", exact=True).first).to_be_visible(
                    timeout=15000
                )

            upload(
                "review.json",
                json.dumps(
                    {
                        "goal_ds_ai": True,
                        "skill_ml_level": "Beginner",
                        "data_provenance": {"synthetic": ["skill_ml_level"]},
                    }
                ).encode(),
                "survey_json",
            )
            page.get_by_role("checkbox", name="Select goal_ds_ai").check()
            page.get_by_text("Additional fields", exact=False).first.click()
            page.get_by_role("textbox", name="/current_semester", exact=True).fill("2")
            page.get_by_role("checkbox", name="Select current_semester").check()
            page.get_by_role("button", name="Confirm selected fields").click()
            expect(
                page.get_by_text("User confirmed · /goal_ds_ai", exact=True)
            ).to_be_visible()
            upload(
                "transcript.pdf",
                document(
                    [
                        [
                            "Academic Transcript",
                            "Institution: IIT Kanpur",
                            "Programme: B.Tech",
                            "Department: Mechanical Engineering",
                            "CPI: 8.5",
                            "Semester 1",
                            "MTH112M Calculus A 6",
                        ]
                    ]
                ),
                "academic_transcript",
            )
            expect(
                page.get_by_text("MTH112M Calculus A 6", exact=True).first
            ).to_be_visible()
            transcript = page.url
            upload(
                "template.pdf",
                document(
                    [
                        [
                            "Curriculum template",
                            "BT",
                            "Semester 3",
                            "ME209 Mechanics 6 credits",
                        ],
                        ["BTH", "Semester 3", "ME999 Research 6 credits"],
                    ]
                ),
                "curriculum_template",
            )
            page.get_by_label("Programme variant").select_option("BT")
            if args.vectors:
                for _ in range(180):
                    status=page.request.get(base+"/api/v1/health/details").json()
                    if status["vector_status"]=="ready" and status["pending_vectors"]==0:break
                    if _ % 15==0:print("Index",status["vector_status"],status["pending_vectors"],status.get("vector_error_type"),flush=True)
                    time.sleep(1)
                else:raise RuntimeError(f"Document indexing did not finish: {status}")
                page.get_by_role("link",name="Memory Explorer",exact=True).click()
                page.get_by_role("button",name="Inspect retrieval").click()
                page.get_by_text("Multi-source retrieval trace",exact=True).click()
                page.get_by_label("Source query",exact=True).fill("In which institution do I study?")
                page.get_by_role("button",name="Trace retrieval").click()
                expect(page.get_by_text("You study at IIT Kanpur.",exact=True)).to_be_visible()
            page.get_by_role("button", name="New conversation").click()
            page.wait_for_url("**/chat/*")
            thread = page.url

            def ask(q, answer):
                page.get_by_label("Your message").fill(q)
                page.get_by_role("button", name="Send message").click()
                expect(
                    page.locator("article.message.assistant p").last
                ).to_contain_text(answer, timeout=10000)

            ask("In which college I study?", "You study at IIT Kanpur.")
            page.locator("article.message.assistant").last.locator("summary").click()
            page.locator("article.message.assistant").last.get_by_role(
                "link", name="transcript.pdf", exact=False
            ).click()
            expect(page).to_have_url(transcript)
            page.goto(thread)
            ask("What is my current CPI?", "8.5")
            ask("Which courses have I completed?", "MTH112M")
            ask(
                "What courses are listed for next semester in my programme template?",
                "ME209",
            )
            ask("What are my learning goals?", "ds ai")
        with server(port, Path(tmp),vectors=args.vectors) as base:
            page.goto(thread)
            ask("Where am I enrolled?", "You study at IIT Kanpur.")
            page.goto(base + "/persona")
            card = page.locator(".memory-card").filter(
                has=page.get_by_role("heading", name="IIT Kanpur", exact=True)
            )
            card.get_by_role("button", name="Edit", exact=True).click()
            page.get_by_role("dialog").get_by_role("textbox").fill("Updated Institute")
            page.get_by_role("button", name="Save correction").click()
            expect(
                page.get_by_role("heading", name="Updated Institute", exact=True)
            ).to_be_visible()
            page.goto(thread)
            ask("Which university do I attend?", "You study at Updated Institute.")
        assert not errors, errors
        browser.close()
        print(
            "Browser verified three uploads, selective survey confirmation, programme variant filtering, five grounded answers, cited source navigation, restart and manual correction."
        )


if __name__ == "__main__":
    main()
