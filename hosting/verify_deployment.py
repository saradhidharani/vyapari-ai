"""Browser walkthrough of a Vyapari deployment, as a signed-out judge would see it.

Not part of the GoDaddy ZIP. Needs Playwright and Microsoft Edge on the machine
running it. The judge password is read from VYAPARI_DEMO_PASSWORD.

    python hosting/verify_deployment.py https://example.com before --storefront <slug> --state state.json
    (restart the backend)
    python hosting/verify_deployment.py https://example.com after --state state.json

"before" signs in as the judge, checks the agency dashboard, opens a client
workspace, creates a paid order, confirms the stock and sales change, switches
clients, and submits a public storefront enquiry. "after" signs in again and
confirms the order, stock, and enquiry are still there.
"""
import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

JUDGE = "judge@vyapari-demo.example"
CLIENT, OTHER_CLIENT, PRODUCT = "Asha Textiles", "Ravi Home Goods", "Handloom Cotton Saree"
results = []


def check(label, condition):
    results.append(bool(condition))
    print(("PASS " if condition else "FAIL ") + label, flush=True)


def rupees(text):
    match = re.search(r"-?₹\s?-?[\d,]+(?:\.\d+)?", text)
    return float(match.group(0).replace("₹", "").replace(",", "").replace(" ", "")) if match else None


def sign_in(page, base, password):
    page.goto(base)
    page.locator("input[name=email]").fill(JUDGE)
    page.locator("input[name=password]").fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.locator(".workspace-select > strong").wait_for(timeout=30_000)


def current_business(page):
    return page.locator(".workspace-select > strong")


def current_role(page):
    return page.locator(".workspace-select > small").inner_text()


def dashboard(page, period="today"):
    page.get_by_role("button", name="Agencies").click()
    board = page.locator("section.agency-dashboard")
    board.locator("table").wait_for(timeout=30_000)
    with page.expect_response(lambda r: "/dashboard" in r.url):
        board.locator("select").select_option(period) if board.locator("select").input_value() != period else \
            board.get_by_role("button", name="Refresh").click()
    page.wait_for_timeout(500)
    return board


def open_client(page, name):
    board = dashboard(page)
    board.locator("tbody tr", has_text=name).get_by_role("button", name="Open workspace").click()
    expect(current_business(page)).to_have_text(name, timeout=30_000)


def product_stock(page, name):
    page.get_by_role("button", name="Products").click()
    row = page.locator("tbody tr", has_text=name).first
    row.wait_for(timeout=30_000)
    return int(row.locator("td").nth(3).inner_text().strip())


def enquiries_text(page):
    page.get_by_role("button", name="Website enquiries").click()
    page.wait_for_timeout(2000)
    return page.locator("main").inner_text()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("base")
    parser.add_argument("phase", choices=("before", "after"))
    parser.add_argument("--storefront", help="Published storefront slug for the enquiry test (before phase)")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()
    base = args.base.rstrip("/")
    password = os.environ.get("VYAPARI_DEMO_PASSWORD", "")
    if not password:
        parser.error("Set VYAPARI_DEMO_PASSWORD")
    shots = args.screenshots
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        errors = []
        context = browser.new_context(viewport={"width": 1400, "height": 1000})  # Signed out: no stored session.
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        sign_in(page, base, password)
        check("judge signs in without a verification code", current_business(page).inner_text() == "Vyapari Demo Studio")

        if args.phase == "before":
            if not args.storefront:
                parser.error("--storefront is required for the before phase")
            board = dashboard(page)
            names = board.locator("tbody tr td:first-child").all_inner_texts()
            check("agency dashboard lists both demo clients", {CLIENT, OTHER_CLIENT} <= set(names))
            combined_before = rupees(board.locator(".stat").first.inner_text())
            if shots:
                page.screenshot(path=str(shots / "1-agency-dashboard.png"), full_page=True)

            open_client(page, CLIENT)
            check("client workspace opens through the agency", "via Vyapari Demo Agency" in current_role(page))
            stock_before = product_stock(page, PRODUCT)

            page.get_by_role("button", name="Orders").click()
            page.get_by_role("button", name="New order").click()
            form = page.locator("form.modal")
            form.locator("select.order-select").nth(0).select_option(index=1)
            product_select = form.locator("select.order-select").nth(1)
            value = product_select.locator("option", has_text=PRODUCT).get_attribute("value")
            product_select.select_option(value)
            form.locator("input[type=number]").fill("1")
            form.locator("select.order-select").last.select_option("Paid")
            if shots:
                page.screenshot(path=str(shots / "2-new-order.png"))
            form.get_by_role("button", name="Save order").click()
            form.wait_for(state="detached", timeout=30_000)
            stock_after = product_stock(page, PRODUCT)
            check(f"paid order deducts stock ({stock_before} → {stock_after})", stock_after == stock_before - 1)

            board = dashboard(page)
            combined_after = rupees(board.locator(".stat").first.inner_text())
            check(f"today's combined net sales rise by the order total ({combined_before} → {combined_after})",
                  combined_before is not None and combined_after is not None and round(combined_after - combined_before) == 1500)

            switcher = page.locator(".business-switch select")
            switcher.select_option(switcher.locator("option", has_text=OTHER_CLIENT).get_attribute("value"))
            expect(current_business(page)).to_have_text(OTHER_CLIENT, timeout=30_000)
            page.get_by_role("button", name="Products").click()
            page.locator("tbody tr").first.wait_for(timeout=30_000)
            products_text = page.locator("main").inner_text()
            check("switching clients shows only that client's products",
                  "Ceramic Serving Bowl" in products_text and PRODUCT not in products_text)

            token = f"Judge check {uuid.uuid4().hex[:8]}"
            visitor = browser.new_context().new_page()
            visitor.on("pageerror", lambda error: errors.append(str(error)))
            visitor.goto(f"{base}/store/{args.storefront}")
            visitor.locator("input[name=name]").fill("Walkthrough Visitor")
            visitor.locator("input[name=phone]").fill("+91 98000 12345")
            visitor.locator("textarea[name=message]").fill(token)
            visitor.get_by_role("button", name="Send enquiry").click()
            visitor.get_by_text("Your enquiry was sent to the business.").wait_for(timeout=30_000)
            check("public storefront accepts an enquiry while signed out", True)
            if shots:
                visitor.screenshot(path=str(shots / "3-storefront-enquiry.png"), full_page=True)

            open_client(page, CLIENT)
            check("enquiry reaches the client's enquiry inbox", token in enquiries_text(page))
            args.state.write_text(json.dumps({"stock": stock_after, "token": token}), encoding="utf-8")
        else:
            state = json.loads(args.state.read_text(encoding="utf-8"))
            open_client(page, CLIENT)
            check("stock change persisted after restart", product_stock(page, PRODUCT) == state["stock"])
            check("enquiry persisted after restart", state["token"] in enquiries_text(page))
            if shots:
                page.screenshot(path=str(shots / "4-after-restart.png"), full_page=True)

        check("no uncaught page errors", not errors)
        browser.close()
    print(f"{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
