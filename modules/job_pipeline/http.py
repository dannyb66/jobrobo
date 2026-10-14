"""Bounded public GET requests and inert HTML/JSON readers shared by adapters."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import ipaddress
import json
import re
import socket
import time
from urllib.parse import urljoin, urlparse


def now():
    return datetime.now(timezone.utc).isoformat()


def public_url(value, base=None):
    if not isinstance(value, str) or not value.strip():
        return None
    value = unescape(value.strip())
    if base:
        value = urljoin(base, value)
    elif value.startswith("//"):
        value = "https:" + value
    elif not value.startswith(("https://", "http://")):
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", value):
            return None
        value = "https://" + value
    try:
        parsed = urlparse(value)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password
            or port not in (None, 80, 443) or hostname in {"localhost", "localhost.localdomain"}
            or hostname.endswith((".local", ".internal", ".localhost"))):
        return None
    try:
        if not ipaddress.ip_address(hostname).is_global:
            return None
    except ValueError:
        pass
    return parsed._replace(fragment="").geturl()


def error(source, code, message, url=None, retryable=False):
    return {"source": source, "code": code, "message": str(message), "url": url, "retryable": retryable}


class FetchError(RuntimeError):
    def __init__(self, code, message, url, retryable=False):
        super().__init__(message)
        self.code, self.url, self.retryable = code, url, retryable


class PublicHTTPClient:
    """Read public pages only; validate redirects and never retry access challenges."""

    def __init__(self, timeout=12, min_interval=0.3, max_bytes=12_000_000):
        import requests
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "JobRobo/1.0 (public job and company research)", "Accept": "application/json,text/html;q=0.9"})
        self.timeout, self.min_interval, self.max_bytes = timeout, min_interval, max_bytes
        self.last_request = {}

    def get(self, url, timeout=None):
        import requests
        for _ in range(5):
            safe = public_url(url)
            if not safe:
                raise FetchError("unsafe_url", "Only public HTTP(S) URLs are supported", url)
            hostname = urlparse(safe).hostname
            try:
                addresses = socket.getaddrinfo(hostname, None)
                if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
                    raise FetchError("unsafe_url", "Address resolves outside the public Internet", safe)
            except socket.gaierror as exc:
                raise FetchError("network", str(exc), safe, True) from exc
            elapsed = time.monotonic() - self.last_request.get(hostname, 0)
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_request[hostname] = time.monotonic()
            try:
                response = self.session.get(safe, timeout=timeout or self.timeout, allow_redirects=False, stream=True)
            except requests.RequestException as exc:
                raise FetchError("network", type(exc).__name__, safe, True) from exc
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise FetchError("invalid_redirect", "Redirect has no Location header", safe)
                url = urljoin(safe, location)
                continue
            body = bytearray()
            try:
                for chunk in response.iter_content(65536):
                    body.extend(chunk)
                    if len(body) > self.max_bytes:
                        raise FetchError("response_too_large", "Public response exceeds size limit", safe)
                response._content = bytes(body)
                response._content_consumed = True
                if "charset=" not in response.headers.get("Content-Type", "").lower():
                    response.encoding = "utf-8"
            finally:
                response.close()
            return response
        raise FetchError("redirect_limit", "Too many public redirects", url)


@dataclass
class Page:
    url: str
    text: str
    data: object = None
    coverage_complete: bool | None = None


def fetch_page(url, client=None, timeout=12):
    safe = public_url(url)
    if not safe:
        raise FetchError("unsafe_url", "Invalid public URL", str(url))
    client = client or PublicHTTPClient(timeout=timeout)
    try:
        response = client.get(safe, timeout=timeout)
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError("network", type(exc).__name__, safe, True) from exc
    status = getattr(response, "status_code", 200)
    actual_url = getattr(response, "url", None) or safe
    if not public_url(actual_url):
        raise FetchError("unsafe_url", "Unsafe redirect destination", str(actual_url))
    if status in {401, 403, 407, 451}:
        raise FetchError("restricted", f"Public access returned HTTP {status}; use an authorized import", actual_url)
    if status == 429:
        raise FetchError("rate_limited", "Public access rate limited; checkpoint retained", actual_url, True)
    if status >= 400:
        raise FetchError("http_error", f"HTTP {status}", actual_url, status >= 500)
    text = getattr(response, "text", "")
    if not isinstance(text, str):
        raise FetchError("invalid_response", "Response is not text", actual_url)
    lowered = text[:20000].lower()
    if any(marker in lowered for marker in ("just a moment...", "cf-chl-", "captcha challenge", "verify you are human")):
        raise FetchError("restricted", "Public page presents an access challenge; use an authorized import", actual_url)
    data = None
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        pass
    return Page(actual_url, text, data)


def render_page(url, render):
    """Renderer injection is for normal public UI rendering, never a challenge bypass."""
    try:
        result = render(url)
    except Exception as exc:
        raise FetchError("render_failed", type(exc).__name__, url, True) from exc
    if isinstance(result, str):
        return Page(url, result)
    if isinstance(result, dict) and isinstance(result.get("html"), str):
        destination = public_url(result.get("url", url))
        if not destination:
            raise FetchError("unsafe_url", "Renderer returned a nonpublic destination", url)
        coverage = result.get("complete") if type(result.get("complete")) is bool else None
        return Page(destination, result["html"], coverage_complete=coverage)
    raise FetchError("render_failed", "Renderer must return HTML or {html, url}", url)


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: object = None

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def text(self, include_scripts=False):
        if not include_scripts and self.tag in {"script", "style"}:
            return ""
        return " ".join(child.text(include_scripts) if isinstance(child, Node) else child for child in self.children)


class Document(HTMLParser):
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node("document")
        self.stack = [self.root]
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, dict(attrs), parent=self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def nodes(self, tag=None):
        return [node for node in self.root.walk() if tag is None or node.tag == tag]


def plain_text(value):
    if not isinstance(value, str):
        return ""
    # Greenhouse content can be HTML encoded twice.
    for _ in range(2):
        value = unescape(value)
    return " ".join(Document(value).root.text().split())


def embedded_json(document):
    """Decode published JSON, data attributes and React flight values without JS eval."""
    values, flight = [], []
    decoder = json.JSONDecoder()
    for node in document.nodes():
        for key, value in node.attrs.items():
            if key.startswith("data-") and isinstance(value, str) and value.lstrip().startswith(("{", "[")):
                try:
                    values.append(json.loads(value))
                except ValueError:
                    pass
        if node.tag != "script":
            continue
        script = node.text(True).strip()
        if node.attrs.get("type") in {"application/json", "application/ld+json"} or node.attrs.get("id") == "__NEXT_DATA__":
            try:
                values.append(json.loads(script))
            except ValueError:
                pass
        for match in re.finditer(r"self\.__next_f\.push\(\s*", script):
            try:
                item, _ = decoder.raw_decode(script[match.end():])
                if isinstance(item, list) and len(item) > 1 and isinstance(item[1], str):
                    flight.append(item[1])
            except ValueError:
                pass
        for match in re.finditer(r"(?:window\.)?[\w.$]+\s*=\s*(?=[\[{])", script):
            try:
                item, _ = decoder.raw_decode(script[match.end():])
                values.append(item)
            except ValueError:
                pass
    # Flight's length-prefixed text frames may contain raw newlines; JSON rows
    # can start immediately after such frames instead of at a line boundary.
    stream = "".join(flight)
    for match in re.finditer(r"[a-f0-9]+:(?:I)?(?=[\[{])", stream):
        try:
            item, _ = decoder.raw_decode(stream[match.end():])
            values.append(item)
        except ValueError:
            pass
    return values


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)
    elif isinstance(value, str) and value.lstrip().startswith(("{", "[")):
        try:
            yield from objects(json.loads(value))
        except ValueError:
            pass
