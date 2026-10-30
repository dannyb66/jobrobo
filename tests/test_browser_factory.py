"""The dedicated Chrome must be reattachable across a resume."""
import unittest
from unittest import mock
from pathlib import Path

import direct_apply


class BrowserFactoryTests(unittest.TestCase):
    def build(self, **kwargs):
        import selenium.webdriver

        with mock.patch.object(selenium.webdriver, "Chrome") as chrome:
            chrome.return_value = "driver"
            direct_apply.browser_factory(**kwargs)()
        return chrome.call_args.kwargs["options"]

    def test_pins_a_debugging_port_so_a_retained_tab_is_reachable(self):
        options = self.build(profile_path="/tmp/p")
        ports = [a for a in options.arguments if a.startswith("--remote-debugging-port=")]
        self.assertEqual(len(ports), 1)
        self.assertNotEqual(ports[0], "--remote-debugging-port=0")

    def test_exposes_the_port_it_chose(self):
        create = direct_apply.browser_factory(profile_path="/tmp/p")
        self.assertIsInstance(create.port, int)
        self.assertGreater(create.port, 0)

    def test_reattaching_needs_no_port_or_profile(self):
        options = self.build(debugger_address="127.0.0.1:9222")
        self.assertEqual(options.debugger_address, "127.0.0.1:9222")
        self.assertFalse([a for a in options.arguments if a.startswith("--user-data-dir")])
