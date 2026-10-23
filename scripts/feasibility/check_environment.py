"""Run with python -m scripts.feasibility.check_environment."""

import importlib
import importlib.metadata
import platform
import sqlite3
import sys

from scripts.feasibility.common import browser_environment, emit, failed

PACKAGES = {
    "fastapi": "fastapi", "pydantic": "pydantic", "sqlalchemy": "sqlalchemy",
    "httpx": "httpx", "groq": "groq", "playwright": "playwright",
    "pdfplumber": "pdfplumber", "jinja2": "jinja2", "pytest": "pytest",
    "python-dotenv": "dotenv", "pypdf": "pypdf",
}


def check() -> dict:
    versions = {}
    for distribution, module in PACKAGES.items():
        importlib.import_module(module)
        versions[distribution] = importlib.metadata.version(distribution)
    browser_environment()
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        with playwright.chromium.launch() as browser:
            page = browser.new_page()
            page.set_content("<title>CareerLens browser smoke</title><p>Ready</p>")
            assert page.title() == "CareerLens browser smoke"
            chromium = browser.version
    with sqlite3.connect(":memory:") as connection:
        assert connection.execute("SELECT 1").fetchone() == (1,)
    from sqlalchemy import create_engine, text
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        engine.dispose()
    return {
        "status": "PASS", "python": platform.python_version(),
        "executable": sys.executable, "os": platform.platform(),
        "machine": platform.machine(), "sqlite": sqlite3.sqlite_version,
        "chromium": chromium, "packages": versions,
        "checks": ["imports", "sqlite_query", "sqlalchemy_sqlite_query", "chromium_launch", "page_interaction"],
    }


if __name__ == "__main__":
    try:
        emit("environment", check())
    except Exception as error:
        raise SystemExit(failed("environment", error))
