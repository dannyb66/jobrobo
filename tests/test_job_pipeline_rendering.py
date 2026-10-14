"""Public-renderer tests use fake Chrome; they never scan websites or log in."""

from contextlib import contextmanager
import os
import socket
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules.job_pipeline.http import FetchError, render_page
from modules.job_pipeline import rendering


def public_dns(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", port))]


class Driver:
    def __init__(self, html="<h1>Public careers</h1>", destination=None):
        self.page_source = html
        self.destination = destination
        self.current_url = None
        self.calls = []
        self.closed = False
        self.failure = None

    def set_page_load_timeout(self, seconds):
        self.calls.append(("page_timeout", seconds))

    def set_script_timeout(self, seconds):
        self.calls.append(("script_timeout", seconds))

    def get(self, url):
        self.calls.append(("get", url))
        if self.failure:
            raise self.failure
        self.current_url = self.destination or url

    def execute_async_script(self, script, bound):
        self.calls.append(("hydrate", bound))

    def quit(self):
        self.closed = True


class PublicRendererTests(unittest.TestCase):
    @contextmanager
    def renderer(self, driver=None, config=None):
        driver = driver or Driver()
        with patch.object(rendering.socket, "getaddrinfo", side_effect=public_dns), \
                patch.object(rendering, "_new_driver", return_value=driver) as factory:
            with rendering.public_renderer(config) as render:
                yield render, driver, factory

    def test_unused_context_never_starts_chrome_or_proxy(self):
        with patch.object(rendering, "_new_driver") as driver, patch.object(rendering, "_PublicProxy") as proxy:
            with rendering.public_renderer():
                driver.assert_not_called()
                proxy.assert_not_called()

    def test_normal_render_is_partial_and_profile_and_browser_are_closed(self):
        with self.renderer(config={"public_render_max_pages": 2, "public_render_timeout_seconds": 3}) as (render, driver, factory):
            result = render("https://example.test/careers")
            self.assertEqual(result, {"html": "<h1>Public careers</h1>", "url": "https://example.test/careers",
                                      "coverage_complete": False, "complete": False})
            profile, proxy = factory.call_args.args
            self.assertTrue(os.path.isdir(profile))
            self.assertTrue(proxy.startswith("http://127.0.0.1:"))
            self.assertIn(("page_timeout", 3), driver.calls)
            render("https://example.test/companies")
            factory.assert_called_once()
        self.assertTrue(driver.closed)
        self.assertFalse(os.path.exists(profile))
        with self.assertRaises(FetchError) as failure:
            render("https://example.test")
        self.assertEqual(failure.exception.code, "render_failed")

    def test_page_budget_is_enforced_and_failures_consume_the_budget(self):
        driver = Driver()
        driver.failure = TimeoutError("slow navigation")
        with self.renderer(driver, {"public_render_max_pages": 1}) as (render, driver, _):
            with self.assertRaises(FetchError) as failure:
                render("https://example.test")
            self.assertEqual(failure.exception.code, "render_failed")
            with self.assertRaises(FetchError) as failure:
                render("https://example.test/next")
            self.assertEqual(failure.exception.code, "pagination_limit")
            self.assertEqual(len([call for call in driver.calls if call[0] == "get"]), 1)
        self.assertTrue(driver.closed)

    def test_unsafe_url_rejected_before_browser_creation(self):
        for url in ("file:///etc/hosts", "http://localhost", "https://127.0.0.1", "https://user:password@example.test"):
            with self.subTest(url=url), self.renderer() as (render, _, factory):
                with self.assertRaises(FetchError) as failure:
                    render(url)
                self.assertEqual(failure.exception.code, "unsafe_url")
                factory.assert_not_called()

    def test_private_dns_and_mixed_dns_rejected_before_browser_creation(self):
        for addresses in (["192.168.1.1"], ["8.8.8.8", "10.0.0.1"]):
            with self.subTest(addresses=addresses), self.renderer() as (render, _, factory):
                records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses]
                with patch.object(rendering.socket, "getaddrinfo", return_value=records):
                    with self.assertRaises(FetchError) as failure:
                        render("https://example.test")
                    self.assertEqual(failure.exception.code, "unsafe_url")
                factory.assert_not_called()

    def test_redirect_destination_is_validated(self):
        with self.renderer(Driver(destination="http://localhost/secret")) as (render, driver, _):
            with self.assertRaises(FetchError) as failure:
                render("https://example.test")
            self.assertEqual(failure.exception.code, "unsafe_url")
        self.assertTrue(driver.closed)

    def test_restricted_challenges_password_pages_and_rate_limits_remain_explicit(self):
        cases = [("<title>Just a moment...</title>", "restricted"),
                 ("<div>Verify you are human</div>", "restricted"),
                 ('<input type="password">', "restricted"),
                 ("<h1>403 Forbidden</h1>", "restricted"),
                 ("<h1>Too many requests</h1>", "rate_limited"),
                 ('<div id="main-frame-error">Page cannot be reached</div>', "network")]
        for html, code in cases:
            with self.subTest(html=html), self.renderer(Driver(html)) as (render, driver, _):
                with self.assertRaises(FetchError) as failure:
                    render_page("https://example.test", render)
                self.assertEqual(failure.exception.code, code)
                self.assertEqual([call[0] for call in driver.calls].count("get"), 1)
        with self.renderer(Driver(destination="https://example.test/login")) as (render, _, _):
            with self.assertRaises(FetchError) as failure:
                render("https://example.test")
            self.assertEqual(failure.exception.code, "restricted")

    def test_driver_start_failure_cleans_profile_and_proxy(self):
        paths = []
        def fail(profile, _):
            paths.append(profile)
            self.assertTrue(os.path.isdir(profile))
            raise RuntimeError("Chrome missing")
        with patch.object(rendering.socket, "getaddrinfo", side_effect=public_dns), patch.object(rendering, "_new_driver", side_effect=fail):
            with rendering.public_renderer() as render:
                with self.assertRaises(FetchError):
                    render("https://example.test")
        self.assertFalse(os.path.exists(paths[0]))

    def test_render_configuration_validation(self):
        for key, values in (("public_render_max_pages", [0, -1, True, "5"]),
                            ("public_render_timeout_seconds", [0, -1, True, "15", float("inf"), float("nan")])):
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    with rendering.public_renderer({key: value}):
                        pass

    def test_chrome_uses_normal_webdriver_and_ephemeral_guest_profile(self):
        options = Mock()
        webdriver = SimpleNamespace(ChromeOptions=Mock(return_value=options), Chrome=Mock(return_value="driver"))
        with patch.dict(sys.modules, {"selenium": SimpleNamespace(webdriver=webdriver)}):
            self.assertEqual(rendering._new_driver("/temporary/profile", "http://127.0.0.1:4321"), "driver")
        arguments = [call.args[0] for call in options.add_argument.call_args_list]
        for expected in ("--guest", "--headless=new", "--user-data-dir=/temporary/profile", "--proxy-server=http://127.0.0.1:4321",
                         "--proxy-bypass-list=<-loopback>", "--disable-quic"):
            self.assertIn(expected, arguments)
        self.assertFalse(any("stealth" in argument or "AutomationControlled" in argument or "ignore-certificate" in argument for argument in arguments))
        self.assertEqual(options.page_load_strategy, "normal")
        webdriver.Chrome.assert_called_once_with(options=options)


class PublicProxyTests(unittest.TestCase):
    def test_proxy_pins_connection_to_validated_public_ip(self):
        upstream = Mock()
        with patch.object(rendering.socket, "getaddrinfo", side_effect=public_dns), patch.object(rendering.socket, "socket", return_value=upstream):
            self.assertIs(rendering._connect_public("https://example.test", 2), upstream)
        upstream.connect.assert_called_once_with(("8.8.8.8", 443))

    def test_proxy_rejects_private_target_before_socket_creation(self):
        record = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
        with patch.object(rendering.socket, "getaddrinfo", return_value=record), patch.object(rendering.socket, "socket") as upstream:
            with self.assertRaises(FetchError) as failure:
                rendering._connect_public("https://example.test", 2)
        self.assertEqual(failure.exception.code, "unsafe_url")
        upstream.assert_not_called()

    def test_proxy_lifecycle_closes_server_and_worker(self):
        with rendering._PublicProxy(2) as proxy:
            self.assertTrue(proxy.thread.is_alive())
            self.assertGreater(proxy.server_address[1], 0)
        self.assertFalse(proxy.thread.is_alive())
        self.assertEqual(proxy.fileno(), -1)

    def test_proxy_rejects_private_redirect_connect_without_transport_fallback(self):
        handler = object.__new__(rendering._ProxyHandler)
        handler.path = "127.0.0.1:443"
        handler.server = SimpleNamespace(timeout_seconds=2, capacity=threading_semaphore())
        handler.send_error = Mock()
        with patch.object(rendering.socket, "socket") as upstream:
            handler.do_CONNECT()
        upstream.assert_not_called()
        handler.send_error.assert_called_once_with(403, "Only public Internet destinations are allowed")


def threading_semaphore():
    import threading
    return threading.BoundedSemaphore(1)


class RenderContractTests(unittest.TestCase):
    def test_explicit_coverage_field_and_legacy_complete_field(self):
        for result, expected in (({"html": "x", "coverage_complete": False, "complete": True}, False),
                                 ({"html": "x", "coverage_complete": True}, True),
                                 ({"html": "x", "complete": True}, True), ({"html": "x"}, None)):
            with self.subTest(result=result):
                self.assertIs(render_page("https://example.test", lambda _: result).coverage_complete, expected)

    def test_renderer_fetch_errors_preserve_unknown_failure_reason(self):
        failure = FetchError("restricted", "Not public", "https://example.test")
        with self.assertRaises(FetchError) as raised:
            render_page("https://example.test", Mock(side_effect=failure))
        self.assertIs(raised.exception, failure)


if __name__ == "__main__":
    unittest.main()
