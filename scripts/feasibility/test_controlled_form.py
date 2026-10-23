"""Local synthetic form interactions and one controlled receipt, never an employer."""

from scripts.feasibility.common import ROOT, OUTPUT, browser_environment, emit, failed


def run() -> dict:
    from playwright.sync_api import sync_playwright

    browser_environment()
    fixture = ROOT / "tests" / "feasibility" / "fixtures" / "application.html"
    pdf = OUTPUT / "synthetic-resume.pdf"
    if not pdf.exists():
        raise FileNotFoundError("Run the synthetic PDF smoke test first")
    with sync_playwright() as playwright:
        with playwright.chromium.launch() as browser:
            context = browser.new_context()
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            page.set_default_timeout(5000)
            page.set_content(fixture.read_text())
            assert page.locator("form").evaluate("form => form.checkValidity()") is False
            page.get_by_role("button", name="Submit local test").click()
            assert page.evaluate("window.receiptCount") == 0
            page.get_by_label("Full name", exact=True).fill("Synthetic Candidate")
            page.get_by_label("Email", exact=True).fill("candidate@example.invalid")
            page.get_by_label("Phone", exact=True).fill("0000000000")
            page.get_by_label("Work type", exact=True).select_option("internship")
            page.get_by_label("Resume", exact=True).set_input_files(str(pdf))
            page.get_by_label("I approve this local test", exact=True).check()
            assert page.locator("form").evaluate("form => form.checkValidity()") is False
            assert page.get_by_label("Answer this required question").evaluate("e => e.validity.valueMissing")
            page.get_by_label("Answer this required question").fill("Synthetic answer, explicitly supplied for this test")
            assert page.locator("form").evaluate("form => form.checkValidity()") is True
            assert page.locator("input[type=file]").evaluate("e => e.files[0].name") == pdf.name
            assert page.evaluate("window.receiptCount") == 0
            paused_before_submit = True
            page.screenshot(path=str(OUTPUT / "controlled-form-ready.png"), full_page=True)
            # Explicitly permitted local-only submission, handled entirely in the fixture DOM.
            page.get_by_role("button", name="Submit local test").click()
            assert page.locator("#receipt").is_visible()
            count = page.evaluate("window.receiptCount")
            assert count == 1
            context.close()
    return {"status": "PASS", "target": "Local controlled fixture, not an employer",
            "network_disabled": True, "synthetic_data_only": True,
            "checks": ["required_field_validation", "text_inputs", "select", "checkbox",
                       "synthetic_pdf_attachment", "missing_answer_pause", "ready_without_submit",
                       "one_controlled_receipt"],
            "paused_before_final_action": paused_before_submit,
            "controlled_receipt_count": count,
            "limitations": ["No durable approval or idempotency implementation in Phase 1",
                             "Local DOM receipt does not prove employer submission"]}


if __name__ == "__main__":
    try:
        emit("controlled-form", run())
    except Exception as error:
        raise SystemExit(failed("controlled-form", error))
