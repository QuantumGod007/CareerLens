"""Read a discovered employer form. Never fills, uploads, clicks or submits."""

from __future__ import annotations

from urllib.parse import urlsplit

from scripts.feasibility.common import OUTPUT, ProbeError, browser_environment, emit, failed
from scripts.feasibility.test_job_source import check_job_url, fetch_jobs, match_jobs

CONTROL_METADATA = """() => Array.from(document.querySelectorAll('input,select,textarea,button'))
  .filter(e => e.type !== 'hidden')
  .map(e => {
    const question = e.closest('.application-question') || e.closest('fieldset');
    const label = Array.from(e.labels || []).map(l => l.innerText.trim()).join(' ') ||
      e.getAttribute('aria-label') || (question && question.innerText.trim()) || e.placeholder || '';
    return {
      tag: e.tagName.toLowerCase(), type: e.type || null, name: e.name || null,
      id: e.id || null, label: label.slice(0, 1000),
      required_native: e.required === true,
      required_aria: e.getAttribute('aria-required') === 'true',
      required_label_marker: /[✱✳*]/.test(label),
      accept: e.getAttribute('accept'), multiple: e.multiple === true,
      options: e.tagName === 'SELECT' ? Array.from(e.options).map(o => o.text.trim()) : [],
      visible: !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length),
      disabled: e.disabled === true
    };
  })"""


def inspect() -> dict:
    from playwright.sync_api import sync_playwright

    browser_environment()
    jobs, _ = fetch_jobs()
    matches = match_jobs(jobs, "Software Engineer Intern", "India")
    if not matches:
        raise ProbeError("NO_SUPPORTED_JOB")
    job = matches[0]
    destination = check_job_url(job.apply_url, job.external_id)
    blocked_hosts, methods_blocked = set(), set()
    allowed_hosts = {"jobs.lever.co", "cdn.lever.co"}
    with sync_playwright() as playwright:
        with playwright.chromium.launch() as browser:
            context = browser.new_context()

            def restrict(route):
                request = route.request
                host = urlsplit(request.url).hostname
                if request.method not in {"GET", "HEAD"}:
                    methods_blocked.add(request.method)
                    route.abort()
                elif host not in allowed_hosts:
                    blocked_hosts.add(host)
                    route.abort()
                else:
                    route.continue_()

            context.route("**/*", restrict)
            page = context.new_page()
            response = page.goto(destination, wait_until="domcontentloaded", timeout=45000)
            if response is None or response.status >= 400:
                raise ProbeError("FORM_UNAVAILABLE")
            check_job_url(page.url, job.external_id)
            page.locator("input[type=file]").first.wait_for(state="attached", timeout=20000)
            controls = page.evaluate(CONTROL_METADATA)
            body = page.locator("body").inner_text()
            form_data = page.locator("form").evaluate_all("forms => forms.map(f => ({method:f.method, action:f.action}))")
            captcha_frames = page.locator("iframe").evaluate_all(
                "frames => frames.map(f => ({title:f.title, src:f.src})).filter(f => /captcha|turnstile/i.test(f.src+' '+f.title))")
            verification_scripts = page.locator("script[src]").evaluate_all(
                "scripts => scripts.map(s => s.src).filter(s => /captcha|turnstile/i.test(s))")
            OUTPUT.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(OUTPUT / "employer-form.png"), full_page=True)
            report = {
                "status": "PASS", "scope": "Read-only live form inspection; submission NOT TESTED",
                "job_id": job.external_id, "title": job.title, "destination": page.url,
                "http_status": response.status, "controls": controls, "forms": form_data,
                "resume_upload_present": any(c["type"] == "file" for c in controls),
                "password_field_present": any(c["type"] == "password" for c in controls),
                "captcha_frames": captcha_frames, "verification_script_urls": verification_scripts,
                "verification_text_present": any(word in body.casefold() for word in ("captcha", "verify you are human")),
                "external_hosts_blocked": sorted(h for h in blocked_hosts if h),
                "non_read_methods_blocked": sorted(methods_blocked),
                "interactions": {"filled_fields": 0, "uploaded_files": 0, "submit_clicks": 0},
                "limitations": [
                    "No employer-side upload or validation tested",
                    "CAPTCHA may appear only during submission; absence is not proof it will not appear",
                    "Blocked third-party scripts may affect dynamic controls or verification",
                    "Required label markers are observations, not authoritative server-side validation",
                ],
            }
            context.close()
    return report


if __name__ == "__main__":
    try:
        emit("application-form", inspect())
    except Exception as error:
        raise SystemExit(failed("application-form", error))
