"""
Grok Autopilot — 2captcha Turnstile Solver
============================================
Solves Cloudflare Turnstile challenges via 2captcha v1 API.

Our key only supports v1 (in.php/res.php), not v2 (createTask).
Method: turnstile
Cost: ~$1.45/1000 solves
"""

import time

import requests

from ..utils.logger import log, log_err, log_ok

# v1 API endpoints
IN_PHP = "https://2captcha.com/in.php"
RES_PHP = "https://2captcha.com/res.php"


def solve_turnstile(
    api_key: str,
    website_url: str,
    website_key: str,
    action: str | None = None,
    cdata: str | None = None,
    timeout: int = 180,
) -> str | None:
    """Solve a Cloudflare Turnstile challenge via 2captcha v1 API.

    Args:
        api_key: 2captcha API key (v1 compatible).
        website_url: Full URL of the page with Turnstile.
        website_key: The sitekey (data-sitekey attribute or from iframe src).
        action: Optional action (data-action).
        cdata: Optional cdata (data-cdata).
        timeout: Max seconds to wait for solution.

    Returns:
        Turnstile token (cf-turnstile-response), or None on failure.
    """
    # Submit task via in.php
    params: dict = {
        "key": api_key,
        "method": "turnstile",
        "sitekey": website_key,
        "pageurl": website_url,
        "json": 1,
    }
    if action:
        params["action"] = action
    if cdata:
        params["data"] = cdata

    try:
        r = requests.post(IN_PHP, data=params, timeout=30).json()
    except requests.RequestException as e:
        log_err(f"   2captcha in.php request failed: {e}")
        return None

    if r.get("status") != 1:
        log_err(f"   2captcha in.php: {r.get('request', r)}")
        return None

    captcha_id = r["request"]
    log(f"   🔄 2captcha solving Turnstile (id={captcha_id})…")

    # Poll res.php for result
    deadline = time.time() + timeout
    time.sleep(10)  # initial wait — Turnstile takes longer than image captcha
    while time.time() < deadline:
        try:
            g = requests.get(
                RES_PHP,
                params={"key": api_key, "action": "get", "id": captcha_id, "json": 1},
                timeout=15,
            ).json()
        except requests.RequestException as e:
            log_err(f"   2captcha poll err: {e}")
            time.sleep(5)
            continue

        if g.get("status") == 1:
            token = g.get("request", "")
            if token and token != "CAPCHA_NOT_READY":
                log_ok(f"   ✅ Turnstile solved: {token[:40]}…")
                return token
        elif g.get("request") == "CAPCHA_NOT_READY":
            time.sleep(5)
            continue
        else:
            log_err(f"   2captcha res.php: {g.get('request', g)}")
            return None

    log_err(f"   2captcha timeout ({timeout}s)")
    return None


async def extract_turnstile_sitekey(page) -> str | None:
    """Extract Turnstile sitekey from window.__captcha_data (set by interceptor).

    Per 2captcha docs: sitekey is in `b.sitekey` of `turnstile.render(a, b)` call.
    We monkey-patch render BEFORE page load to capture it.
    """
    try:
        data = await page.evaluate(
            "() => window.__captcha_data ? JSON.stringify(window.__captcha_data) : null"
        )
        if data:
            import json
            d = json.loads(data)
            if d.get("sitekey"):
                return d["sitekey"]
        return None
    except Exception:
        return None


INTERCEPT_SCRIPT = """
(() => {
    if (window.__captcha_intercept_installed) return;
    window.__captcha_intercept_installed = true;
    window.__captcha_data = null;

    // Monkey-patch turnstile.render to capture sitekey + callback
    const _waitForTurnstile = () => {
        if (window.turnstile && typeof window.turnstile.render === 'function' && !window.turnstile._patched) {
            const _origRender = window.turnstile.render;
            window.turnstile.render = function(container, params) {
                // Capture the data we need for 2captcha
                window.__captcha_data = {
                    sitekey: params.sitekey,
                    action: params.action || null,
                    cData: params.cData || null,
                    callback: typeof params.callback === 'function' ? 'function' : null,
                    hasCallback: !!params.callback,
                    container: typeof container === 'string' ? container : 'element'
                };
                // Store callback for later token injection
                if (typeof params.callback === 'function') {
                    window.__captcha_callback = params.callback;
                }
                console.log('[CAPTCHA] intercepted turnstile.render:', JSON.stringify(window.__captcha_data));
                return _origRender.apply(this, arguments);
            };
            window.turnstile._patched = true;
        } else {
            setTimeout(_waitForTurnstile, 50);
        }
    };
    _waitForTurnstile();
})();
"""


async def inject_turnstile_token(page, token: str) -> bool:
    """Inject Turnstile token via stored callback + hidden input.

    Per 2captcha docs: call the callback function captured from turnstile.render.
    Also set hidden input as fallback.
    """
    try:
        result = await page.evaluate(
            """(token) => {
                const log = [];
                // 1) Call captured callback (preferred method per 2captcha docs)
                if (typeof window.__captcha_callback === 'function') {
                    try {
                        window.__captcha_callback(token);
                        log.push('callback-called');
                    } catch(e) { log.push('callback-err:' + e.message); }
                }
                // 2) Set hidden input as fallback
                const inp = document.querySelector('input[name="cf-turnstile-response"]');
                if (inp) {
                    inp.value = token;
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                    inp.dispatchEvent(new Event('change', {bubbles: true}));
                    log.push('hidden-input');
                }
                return log;
            }""",
            token,
        )
        log(f"   🔧 Turnstile token injected: {result}")
        return True
    except Exception as e:
        log_err(f"   Turnstile injection failed: {e}")
        return False