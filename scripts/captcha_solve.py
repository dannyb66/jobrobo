"""Run CaptchaKraken against one live Chrome tab over CDP.

Executed by the 3.11 interpreter in `.venv-captchakraken`, because
`captchakraken` requires 3.11+ while the application runs on 3.10. The parent
process owns the browser; this only attaches, solves, and reports.

The solver's own `is_solved` is self-reported, so every rung is returned
separately and the caller decides. Nothing here clicks Submit.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Google now serves reCAPTCHA *Enterprise* on `/recaptcha/enterprise/anchor`.
# The vendor table only names the classic `/recaptcha/api2/...` paths, so every
# enterprise widget matched nothing and detection reported "no challenge".
# Patch the table before the solver builds anything; ids (box/checked/fresh/
# submit) are identical across both editions.
ENTERPRISE_PATCHES = {
    "recaptcha": {
        "challenge": ('iframe[src*="recaptcha"][src*="bframe"]',),
        "checkbox": ('iframe[src*="recaptcha"][src*="anchor"]:not([src*="size=invisible"])',),
    },
}


LEVELS = ("detected", "model_response", "token_present", "challenge_cleared")

TOKEN_SELECTORS = (
    '[name="g-recaptcha-response"]',
    '[name="h-captcha-response"]',
    '[name="cf-turnstile-response"]',
)

PROVIDER_MARKERS = (
    ("hcaptcha", "hcaptcha"),
    ("recaptcha", "recaptcha"),
    ("turnstile", "turnstile"),
)

CHALLENGE_PROBE = r"""(() => {
 const visible=e=>!!e.getClientRects().length&&getComputedStyle(e).visibility!=='hidden';
 const frames=[...document.querySelectorAll('iframe')].filter(visible);
 const provider=frames.some(e=>/hcaptcha/i.test(e.src+' '+e.title))?'hcaptcha':
   frames.some(e=>/recaptcha/i.test(e.src+' '+e.title))?'recaptcha':
   frames.some(e=>/turnstile|cloudflare/i.test(e.src+' '+e.title))?'turnstile':null;
 const boxes=frames.map(e=>e.getBoundingClientRect());
 const overlay=frames.some(e=>/bframe|challenge|hcaptcha/i.test(e.src+' '+e.title)&&e.getBoundingClientRect().height>100);
 const invisible=e=>new URL(e.src||'about:blank',location.href).searchParams.get('size')==='invisible';
 const widget=frames.some((e,i)=>!invisible(e)&&/captcha|turnstile|challenge/i.test(e.src+' '+e.title)&&boxes[i].height>=40&&boxes[i].width>=150);
 const text=(document.body?.innerText||'').slice(0,12000);
 return {provider, active:overlay||widget||/verify you are human|performing security verification/i.test(text)};
})()"""


def patch_selectors() -> bool:
    """Widen recaptcha selectors to classic *and* enterprise, then rebuild
    every frozen derivative.

    ``page_solver`` imports ``SELECTORS`` and ``WIDGET_PROBES`` by value, and
    ``VENDORS`` is frozen from the table at import. Mutating the mapping alone
    changes nothing, so each derivative is rebuilt in place.
    """
    try:
        from captchakraken import selectors as table
    except Exception:
        return False
    for vendor_name, fields in ENTERPRISE_PATCHES.items():
        vendor = next((key for key in table.SELECTORS
                       if str(getattr(key, "value", key)) == vendor_name), None)
        if vendor is None:
            return False
        current = table.SELECTORS[vendor]
        merged = dict(getattr(current, "__dict__", {}))
        for name, selectors in fields.items():
            merged[name] = tuple(dict.fromkeys((*getattr(current, name, ()), *selectors)))
        try:
            table.SELECTORS[vendor] = type(current)(**merged)
        except Exception:
            return False

    table.VENDORS = tuple(table.SELECTORS.items())
    table.WIDGET_PROBES = tuple(
        table.WidgetProbe(vendor, role, selector)
        for role, key in ((table.FrameRole.CHALLENGE, "challenge"),
                          (table.FrameRole.CHECKBOX, "checkbox"),
                          (table.FrameRole.UNKNOWN, "widget"))
        for vendor, vendor_selectors in table.VENDORS
        for selector in getattr(vendor_selectors, key))
    from captchakraken import page_solver
    for target in (table, page_solver):
        for name in ("SELECTORS", "VENDORS", "WIDGET_PROBES"):
            setattr(target, name, getattr(table, name))
    for name in ("ENCLAVE_SELECTORS", "RESPONSE_SELECTORS", "ACCEPTED_SELECTORS",
                 "PIECE_SELECTORS", "SLIDER_HANDLE_SELECTORS", "SUBMIT_SELECTORS",
                 "TEXT_INPUT_SELECTORS", "TEXT_INPUT_VENDOR_SELECTORS"):
        builder = getattr(table, "_of_every_vendor", None)
        if builder is None:
            break
        key = name.replace("_SELECTORS", "").lower()
        try:
            built = tuple(builder(key))
        except Exception:
            continue
        setattr(table, name, built)
        setattr(page_solver, name, built)
    return True


# Some boards (Ashby among them) ship the widget with `visibility: hidden` on
# every ancestor and never un-hide it, so Playwright's visible filter excludes
# a widget that is genuinely there and blocking submit. Un-hiding the ancestors
# is cosmetic here: the solve still targets the real frames.
#
# Only the *checkbox* frame may be un-hidden unconditionally. An invisible
# reCAPTCHA keeps a bframe in the DOM from first paint, but it is empty and
# 150px tall until Submit runs the widget and the vendor deals a real board
# (300x480). Force-showing that stub made detection pick an empty challenge
# frame and every model answer landed on a blank image.
FORCE_VISIBLE = r"""(() => {
 const PAINTED_CHALLENGE = 200;
 let changed = 0;
 for (const frame of document.querySelectorAll('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="turnstile"]')) {
   const checkbox = /anchor|hcaptcha|turnstile/i.test(frame.src) && !/bframe|challenge/i.test(frame.src);
   const painted = frame.getBoundingClientRect().height >= PAINTED_CHALLENGE;
   if (!checkbox && !painted) continue;
   let node = frame;
   while (node && node !== document.body) {
     if (node.style && (getComputedStyle(node).visibility === 'hidden' || getComputedStyle(node).display === 'none')) {
       node.style.visibility = 'visible';
       node.style.display = 'block';
       changed++;
     }
     node = node.parentElement;
   }
 }
 return changed;
})()"""


# Once the challenge is cleared the widget is dead weight, and the ancestors we
# un-hid above stay painted over the form: the 754x150 bframe then swallows the
# submit click. Collapsing it after a clear gives the button its hit area back.
HIDE_WIDGET = r"""(() => {
 let hidden = 0;
 for (const frame of document.querySelectorAll('iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="turnstile"]')) {
   const host = frame.closest('div');
   if (host) { host.style.display = 'none'; hidden++; }
 }
 return hidden;
})()"""


def hide_widget(page) -> bool:
    try:
        return bool(page.evaluate(HIDE_WIDGET))
    except Exception:
        return False


def force_visible(page) -> bool:
    try:
        return bool(page.evaluate(FORCE_VISIBLE))
    except Exception:
        return False


def token_length(page) -> int:
    for selector in TOKEN_SELECTORS:
        try:
            value = page.evaluate(
                "(sel)=>{const e=document.querySelector(sel);return e&&e.value?e.value.length:-1}",
                selector,
            )
        except Exception:
            continue
        if isinstance(value, int) and value > 0:
            return value
    return -1


def probe(page) -> dict:
    try:
        state = page.evaluate(CHALLENGE_PROBE)
        if isinstance(state, dict):
            return state
    except Exception:
        pass
    return {"provider": None, "active": True}


def provider_from_frames(page) -> str | None:
    try:
        for frame in page.frames:
            for marker, name in PROVIDER_MARKERS:
                if marker in (frame.url or ""):
                    return name
    except Exception:
        pass
    return None


def challenge_painted(page) -> bool:
    """An empty bframe is a promise, not a board: the vendor draws it after Submit."""
    try:
        for frame in page.frames:
            if "bframe" not in (frame.url or "") and "challenge" not in (frame.url or ""):
                continue
            try:
                if (frame.inner_text("body") or "").strip():
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def set_levels(levels: dict, **flags) -> None:
    for key, value in flags.items():
        if value:
            levels[key] = True


def grid_solver_class():
    """``PageSolver`` with the 3x3-only gate relaxed.

    reCAPTCHA serves both a real 4x4 board and a dynamic 3x3 that fades between
    screens. ``_solve_single`` only takes the tile-aware grid loop when
    ``grid["size"] == 3``; every other count falls through to the generic
    one-shot path, which clicks the answer once and never watches the tiles
    swap. The grid loop itself is cell-count agnostic (it maps each answer box
    back to a cell), so the size is only a gate key here.

    A board mid-fade still has all 16 cells on screen, so the count is also
    sampled until it repeats before being believed.
    """
    from captchakraken.page_solver import PageSolver

    class GridSolver(PageSolver):
        def _get_grid_boxes(self, element):
            grid, last = None, None
            for _ in range(8):
                grid = super()._get_grid_boxes(element)
                if not grid:
                    return None
                count = len(grid["boxes"])
                if count == last and count in (9, 16):
                    break
                last = count
                time.sleep(0.25)
            if grid:
                grid["size"] = 3
            return grid

    return GridSolver


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp", required=True, help="CDP websocket URL of the live browser")
    parser.add_argument("--url", default="", help="URL of the tab to solve; first page is used when omitted")
    parser.add_argument("--screenshot", help="Where to write the final screenshot")
    parser.add_argument("--detection-timeout-ms", type=int, default=15000)
    parser.add_argument("--overall-timeout-ms", type=int, default=120000)
    parser.add_argument("--max-responses", type=int, default=5, help="Vendor bills per response; hard cap")
    parser.add_argument("--expect-provider", help="Fail fast as unsupported on a different provider")
    parser.add_argument("--wait-painted-ms", type=int, default=0,
                        help="Wait this long for an already-present challenge frame to draw a board")
    args = parser.parse_args(argv)

    from captchakraken import CaptchaKrakenAPIError as APIError
    from playwright.sync_api import sync_playwright
    from requests import RequestException

    levels: dict = {}
    provider = None
    responses = 0
    started = time.monotonic()
    status, detail = "error", ""

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(args.cdp, timeout=30000)
        pages = [candidate for context in browser.contexts for candidate in context.pages]
        page = next((candidate for candidate in pages if args.url and candidate.url == args.url), None)
        if page is None and pages:
            page = pages[0]
        if page is None:
            print(json.dumps({"status": "error", "detail": "no attachable page"}))
            return 0
        try:
            page.bring_to_front()
        except Exception:
            pass

        force_visible(page)
        state = probe(page)
        provider = state.get("provider") or provider_from_frames(page)

        # The ancestors of an empty challenge frame are hidden too, so the first
        # pass above skips it. Once Submit runs the widget the vendor draws a real
        # board and only then is un-hiding it correct.
        waited = 0
        while args.wait_painted_ms and waited < args.wait_painted_ms and not challenge_painted(page):
            time.sleep(0.25)
            waited += 250
            force_visible(page)
            state = probe(page)
            provider = state.get("provider") or provider_from_frames(page)

        set_levels(levels, detected=bool(state.get("active")) or bool(provider))

        if not levels.get("detected"):
            status, detail = "no_challenge", "no challenge widget found within the detection window"
        elif args.expect_provider and provider and provider != args.expect_provider:
            status, detail = "unsupported", f"provider {provider} does not match expected {args.expect_provider}"
        else:
            try:
                patch_selectors()
                force_visible(page)
                from captchakraken.page_solver import (
                    CaptchaSolveError,
                    NoCaptchaFoundError,
                    PageSolver,
                    PageSolverConfig,
                    UnsupportedChallengeError,
                    VendorBlockedError,
                )

                config = PageSolverConfig(
                    detection_timeout_ms=args.detection_timeout_ms,
                    overall_solve_timeout_ms=args.overall_timeout_ms,
                    max_solve_loops=args.max_responses,
                )
                outcome = grid_solver_class()(config).solve(page)
                responses = len(getattr(outcome, "token_usage", []) or [])
                after = probe(page)
                token_now = token_length(page)
                cleared = not after.get("active") or token_now > 0
                set_levels(levels, model_response=responses > 0,
                           token_present=token_now > 0, challenge_cleared=cleared)
                if cleared:
                    hide_widget(page)
                    status, detail = "cleared", "challenge no longer active or response token present"
                else:
                    status, detail = "rejected", "solver finished but the widget is still active and has no token"
            except NoCaptchaFoundError as error:
                status, detail = "no_challenge", str(error)[-400:]
            except UnsupportedChallengeError as error:
                status, detail = "unsupported", str(error)[-400:]
            except VendorBlockedError as error:
                status, detail = "blocked", str(error)[-400:]
            except APIError as error:
                # A refused/undeniable call is not a board the model got wrong.
                status, detail = "error", f"{getattr(error, 'code', None) or type(error).__name__}: {error}"[-400:]
            except RequestException as error:
                status, detail = "error", f"cannot reach the solver API: {type(error).__name__}: {error}"[-400:]
            except CaptchaSolveError as error:
                status, detail = "rejected", str(error)[-400:]
            except Exception as error:
                status, detail = "error", f"{type(error).__name__}: {error}"[-400:]

        final_token = token_length(page)
        if args.screenshot:
            try:
                Path(args.screenshot).parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=args.screenshot, full_page=False)
            except Exception:
                args.screenshot = None
        try:
            host = (page.url or "").split("/")[2]
        except Exception:
            host = ""

    print(json.dumps({
        "status": status,
        "detail": detail,
        "provider": provider,
        "levels": [name for name in LEVELS if levels.get(name)],
        "token_length": final_token,
        "responses": responses,
        "elapsed_ms": round((time.monotonic() - started) * 1000),
        "host": host,
        "screenshot": args.screenshot,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
