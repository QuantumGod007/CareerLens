# Application form validation

Executed 23 October 2026, India Standard Time. Status: PASS for read-only live inspection and controlled local interactions. Employer upload, challenge handling, submission and receipt verification are NOT TESTED.

Playwright opened the real [Engineering Intern application](https://jobs.lever.co/drivetrain/bc1c17bc-86ac-4f00-a1e3-0eb85aae4fdc/apply), HTTP 200. No employer fields were filled, files uploaded or submit controls clicked.

| Observed field | Native required | Later source |
| --- | --- | --- |
| Resume/CV upload | False in observed DOM | Exact reviewed PDF; server requirements unresolved |
| Full name | True | Confirmed profile |
| Email | True | Confirmed profile |
| Phone | True | Confirmed profile or explicit answer |
| Current location | True | Confirmed explicit answer |
| Current company | True | Ask for current status; do not invent an employer for a fresher |
| LinkedIn URL | True | Confirmed URL or explicit answer |

The form has one full-name field, a visible submit control and a hidden hCaptcha submit control. No native selects, checkboxes, consent controls, textareas or password fields appeared in this snapshot. Login was not needed to reach it. Required markers were recorded separately from native/ARIA requirements; server validation was not exercised.

An hCaptcha script reference is present. The inspection allows configured resource hosts and GET/HEAD only, blocking hCaptcha, analytics, a logo host and a background POST. The screenshot therefore has a missing logo. Blocked scripts can affect dynamic controls and verification, so this snapshot cannot establish submission compatibility or absence of challenges. CAPTCHA must not be bypassed. Location autocomplete and conditional questions need later testing.

Recommendation: retain this as a form-preparation candidate, with a visible manual-intervention path. Do not call it a validated autonomous submission integration.

Separately, the network-disabled local fixture passed text/dropdown/checkbox entry, synthetic PDF attachment, required-answer detection, a pause before final action and one local DOM receipt. The initial dropdown-label failure was fixed and rerun successfully. This is browser feasibility evidence, not employer submission or durable consent/duplicate protection.

Local evidence: `data/feasibility/application-form.json`, `employer-form.png`, `controlled-form.json` and `controlled-form-ready.png`. Run the PDF probe before the controlled-form probe. Commands are in the [operation guide](../backend/README.md#tests-and-diagnostics).
