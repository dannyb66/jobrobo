"""Optional ordinary Chrome rendering of public pages, with no authenticated profile.

The renderer captures one normally loaded DOM per request. It never clicks login,
challenge, application, or pagination controls and cannot attest full directory
coverage. A local validating proxy keeps redirects and page subresources on
public Internet addresses without intercepting TLS or bypassing access controls.
"""

from contextlib import contextmanager, ExitStack
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import math
import re
import select
import socket
import threading
import time
from tempfile import TemporaryDirectory
from urllib.parse import urlparse

from .http import Document, FetchError, public_url


MAX_BYTES = 12_000_000


def _setting(config, name, default):
    return config.get(name, default) if isinstance(config, dict) else getattr(config, name, default)


def _public_addresses(url):
    safe = public_url(url)
    if not safe:
        raise FetchError("unsafe_url", "Only public HTTP(S) URLs can be rendered", str(url))
    parsed = urlparse(safe)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError("network", "Public hostname could not be resolved", safe, True) from exc
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise FetchError("unsafe_url", "Render destination resolves outside the public Internet", safe)
    return safe, addresses


def _connect_public(url, timeout):
    safe, addresses = _public_addresses(url)
    deadline = time.monotonic() + timeout
    for family, kind, protocol, _, address in addresses:
        upstream = socket.socket(family, kind, protocol)
        try:
            upstream.settimeout(max(0.01, deadline - time.monotonic()))
            # Connect to the already validated address, avoiding a second DNS lookup.
            upstream.connect(address)
            return upstream
        except OSError:
            upstream.close()
            if time.monotonic() >= deadline:
                break
    raise FetchError("network", "Could not connect to public render destination", safe, True)


class _PublicProxy(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, timeout):
        super().__init__(("127.0.0.1", 0), _ProxyHandler)
        self.timeout_seconds = timeout
        self.stopping = threading.Event()
        self.capacity = threading.BoundedSemaphore(32)
        self.thread = None

    def __enter__(self):
        self.thread = threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stopping.set()
        self.shutdown()
        self.server_close()
        self.thread.join(timeout=1)

    @property
    def address(self):
        return "http://127.0.0.1:" + str(self.server_address[1])


class _ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def setup(self):
        self.request.settimeout(self.server.timeout_seconds)
        super().setup()

    def _relay(self, upstream):
        deadline, total = time.monotonic() + self.server.timeout_seconds, 0
        while not self.server.stopping.is_set() and time.monotonic() < deadline:
            ready, _, _ = select.select([self.connection, upstream], [], [], min(0.1, max(0, deadline - time.monotonic())))
            for source in ready:
                chunk = source.recv(65536)
                if not chunk:
                    return
                total += len(chunk)
                if total > MAX_BYTES:
                    return
                target = upstream if source is self.connection else self.connection
                target.sendall(chunk)

    def _forward(self, tunnel=False):
        self.close_connection = True
        if not self.server.capacity.acquire(blocking=False):
            self.send_error(503, "Public render connection limit")
            return
        try:
            if tunnel:
                # Only ordinary TLS destinations; Chrome never gets a direct fallback.
                destination = "https://" + self.path
                if urlparse(destination).port != 443:
                    raise FetchError("unsafe_url", "Only HTTPS port 443 is supported", destination)
            else:
                destination = self.path
                if urlparse(destination).scheme != "http":
                    raise FetchError("unsafe_url", "Expected an HTTP proxy URL", destination)
            upstream = _connect_public(destination, self.server.timeout_seconds)
            with upstream:
                if tunnel:
                    self.send_response(200, "Connection established")
                    self.end_headers()
                else:
                    parsed = urlparse(destination)
                    target = parsed.path or "/"
                    if parsed.query:
                        target += "?" + parsed.query
                    headers = [(key, value) for key, value in self.headers.items()
                               if key.lower() not in {"connection", "proxy-connection", "proxy-authorization", "host"}]
                    headers.extend([("Host", parsed.netloc), ("Connection", "close")])
                    request = "GET " + target + " HTTP/1.1\r\n" + "".join(key + ": " + value + "\r\n" for key, value in headers) + "\r\n"
                    upstream.sendall(request.encode("latin-1"))
                self._relay(upstream)
        except FetchError:
            self.send_error(403, "Only public Internet destinations are allowed")
        except (OSError, ValueError):
            # A disconnected tab needs no retry or alternate transport.
            pass
        finally:
            self.server.capacity.release()

    def do_CONNECT(self):
        self._forward(tunnel=True)

    def do_GET(self):
        self._forward()

    def do_POST(self):
        self.close_connection = True
        self.send_error(405, "Public renderer does not submit forms")


def _new_driver(profile_path, proxy_url):
    # Do not import the application's open_chrome module: it uses the real profile
    # and may configure stealth. Selenium is optional until rendering is called.
    from selenium import webdriver
    options = webdriver.ChromeOptions()
    for argument in ("--headless=new", "--guest", "--disable-background-networking", "--disable-sync",
                     "--disable-quic", "--disable-extensions", "--no-first-run", "--no-default-browser-check",
                     "--force-webrtc-ip-handling-policy=disable_non_proxied_udp", "--proxy-bypass-list=<-loopback>",
                     "--user-data-dir=" + profile_path, "--proxy-server=" + proxy_url):
        options.add_argument(argument)
    options.add_experimental_option("prefs", {"download_restrictions": 3, "credentials_enable_service": False,
                                               "profile.password_manager_enabled": False})
    options.page_load_strategy = "normal"
    return webdriver.Chrome(options=options)


def _check_page(url, html):
    destination, _ = _public_addresses(url)
    lowered = html[:20000].casefold()
    if any(marker in lowered for marker in ("just a moment...", "cf-chl-", "captcha challenge", "verify you are human",
                                           "access denied", "authentication required")):
        raise FetchError("restricted", "Public page presents an access restriction; use an authorized import", destination)
    document = Document(html)
    if any(node.attrs.get("id") == "main-frame-error" for node in document.nodes()) or "chrome-error://chromewebdata" in lowered:
        raise FetchError("network", "Chrome could not load the public page", destination, True)
    if re.search(r"/(?:login|log-in|signin|sign-in|checkpoint|challenge)(?:/|$)", urlparse(destination).path, re.I):
        raise FetchError("restricted", "Public renderer does not authenticate or solve challenges", destination)
    headings = [node.text().strip().casefold() for node in document.nodes() if node.tag in {"h1", "title"}]
    if any(text in {"403 forbidden", "forbidden", "unauthorized", "access denied"} or "http error 403" in text for text in headings):
        raise FetchError("restricted", "Public page denies access; use an authorized import", destination)
    if any("too many requests" in text or "http error 429" in text for text in headings):
        raise FetchError("rate_limited", "Public render was rate limited; checkpoint retained", destination, True)
    if any(node.tag == "input" and node.attrs.get("type", "").casefold() == "password" for node in document.nodes()):
        raise FetchError("restricted", "Public renderer does not authenticate", destination)
    if len(html.encode("utf-8")) > MAX_BYTES:
        raise FetchError("response_too_large", "Rendered public page exceeds size limit", destination)
    return destination


@contextmanager
def public_renderer(config=None):
    """Yield a bounded callable. The service opts in before entering this context.

    Chrome is created only on the first valid render call, in a temporary guest
    profile, and always closed when the context exits. Failures raise FetchError;
    callers retain partial observations and unknown coverage.
    """
    max_pages = _setting(config, "public_render_max_pages", 5)
    timeout = _setting(config, "public_render_timeout_seconds", 15)
    if type(max_pages) is not int or max_pages < 1:
        raise ValueError("public_render_max_pages must be a positive integer")
    if type(timeout) not in {int, float} or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("public_render_timeout_seconds must be a positive finite number")
    driver, rendered, active = None, 0, True
    with ExitStack() as stack:
        def render(url):
            nonlocal driver, rendered
            if not active:
                raise FetchError("render_failed", "Public renderer context is closed", str(url))
            if rendered >= max_pages:
                raise FetchError("pagination_limit", "Public render page limit reached; checkpoint retained", str(url), True)
            safe, _ = _public_addresses(url)
            rendered += 1
            try:
                if driver is None:
                    profile = stack.enter_context(TemporaryDirectory(prefix="jobrobo-public-render-"))
                    proxy = stack.enter_context(_PublicProxy(timeout))
                    driver = _new_driver(profile, proxy.address)
                driver.set_page_load_timeout(timeout)
                driver.set_script_timeout(timeout)
                deadline = time.monotonic() + timeout
                driver.get(safe)
                # A short quiet DOM interval permits ordinary hydration, without
                # clicking controls or guessing that a catalogue is exhaustive.
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FetchError("render_failed", "Public render exceeded its timeout", safe, True)
                driver.set_script_timeout(remaining)
                driver.execute_async_script("""
                    const done = arguments[arguments.length - 1];
                    let quiet, hard, observer;
                    const finish = () => { clearTimeout(quiet); clearTimeout(hard); observer.disconnect(); done(); };
                    observer = new MutationObserver(() => { clearTimeout(quiet); quiet = setTimeout(finish, 250); });
                    observer.observe(document.documentElement, {childList:true, subtree:true, characterData:true});
                    quiet = setTimeout(finish, 250);
                    hard = setTimeout(finish, arguments[0]);
                """, min(1000, remaining * 500))
                html = driver.page_source
                if not isinstance(html, str):
                    raise FetchError("invalid_response", "Rendered DOM is not HTML text", safe)
                destination = _check_page(driver.current_url, html)
                return {"html": html, "url": destination, "coverage_complete": False, "complete": False}
            except FetchError:
                raise
            except Exception as exc:
                raise FetchError("render_failed", "Ordinary public rendering failed: " + type(exc).__name__, safe, True) from exc

        try:
            yield render
        finally:
            active = False
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
