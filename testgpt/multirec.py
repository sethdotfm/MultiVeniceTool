#!/usr/bin/env python3
"""
Multi-camera REC for Sony VENICE 2 using Playwright.

Opens three browser pages to the camera web UIs and executes:
    document.getElementById("BUTTON_REC_BUTTON").click();

So we don't fight X-Frame-Options or CORS – we just drive the real GUI.
"""

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# --------------------------------------------------------------------
# CONFIG – EDIT THESE
# --------------------------------------------------------------------
CAMERAS = [
    # Use the URL you normally open in the browser:
    #"http://172.17.80.101/rmt.html",
    #"http://172.17.80.102/rmt.html",
    "http://172.17.80.103/rmt.html",
]

HTTP_USERNAME = "admin"       # same as you use in the browser
HTTP_PASSWORD = "PASSWORD"   # ditto

REC_BUTTON_ID = "BUTTON_REC_BUTTON"   # you said this works in console
# If you later find a STOP ID, add it here:
STOP_BUTTON_ID = "BUTTON_REC_STOP"    # example; update once you know
# --------------------------------------------------------------------


def open_cameras(playwright):
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(
        http_credentials={"username": HTTP_USERNAME, "password": HTTP_PASSWORD}
    )

    pages = []
    for url in CAMERAS:
        page = context.new_page()
        print(f"Opening {url} ...")
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        pages.append(page)

    # Give the UI a moment to fully settle
    for page in pages:
        try:
            # If the button is present, wait for it as a sanity check
            page.wait_for_selector(f"#{REC_BUTTON_ID}", timeout=15000)
        except PlaywrightTimeoutError:
            print("Warning: REC button not found in time on one page; "
                  "the JS click may still work if the ID is correct.")

    return browser, pages


def click_button_on_all(pages, element_id):
    js = f"""
        (function() {{
            var el = document.getElementById({element_id!r});
            if (!el) {{
                return "Element not found: " + {element_id!r};
            }}
            el.click();
            return "Clicked " + {element_id!r};
        }})()
    """
    for i, page in enumerate(pages):
        try:
            result = page.evaluate(js)
            print(f"Camera {i+1}: {result}")
        except Exception as e:
            print(f"Camera {i+1}: ERROR executing JS: {e}")


def main():
    with sync_playwright() as p:
        browser, pages = open_cameras(p)

        print("\nAll camera UIs opened.")
        print("Press Enter to START recording on all cameras...")
        input()
        click_button_on_all(pages, REC_BUTTON_ID)

        print("\nIf you have a STOP button ID configured, press Enter to STOP recording...")
        input()
        if STOP_BUTTON_ID:
            click_button_on_all(pages, STOP_BUTTON_ID)
        else:
            print("STOP_BUTTON_ID is not set. Edit the script once you know it.")

        print("\nPress Enter to close the browser windows and exit...")
        input()
        browser.close()


if __name__ == "__main__":
    main()
