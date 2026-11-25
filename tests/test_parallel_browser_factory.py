"""Local profile/endpoint isolation without starting Chrome."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from selenium.common.exceptions import WebDriverException

from direct_apply import browser_factory


class ParallelBrowserFactoryTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve() / 'profile'

    @staticmethod
    def driver(port):
        return Mock(capabilities={'goog:chromeOptions': {'debuggerAddress': f'localhost:{port}'}})

    def test_workers_have_distinct_profiles_and_lazy_ports(self):
        with patch('direct_apply._free_port', side_effect=[12341, 12342]) as allocate, \
             patch('direct_apply._port_is_bound', return_value=False), \
             patch('selenium.webdriver.Chrome', side_effect=[self.driver(12341), self.driver(12342)]) as chrome:
            factories = [browser_factory(self.base, worker_index=i) for i in (1, 2)]
            allocate.assert_not_called()
            self.assertTrue(all(factory.port is None for factory in factories))
            for factory in factories:
                factory()
            self.assertEqual([factory.port for factory in factories], [12341, 12342])
            for index, call in enumerate(chrome.call_args_list, 1):
                options = call.kwargs['options']
                profile = self.base.with_name(f'profile-w{index}')
                self.assertTrue(profile.is_dir())
                self.assertIn('--user-data-dir=' + str(profile), options.arguments)
                self.assertIn(f'--remote-debugging-port={12340 + index}', options.arguments)
            self.assertFalse(self.base.exists())

    def test_single_worker_keeps_base_profile_and_records_actual_port(self):
        with patch('direct_apply._free_port', return_value=12341), \
             patch('direct_apply._port_is_bound', return_value=False), \
             patch('selenium.webdriver.Chrome', return_value=self.driver(12342)):
            factory = browser_factory(self.base)
            factory()
        self.assertEqual(factory.profile_path, str(self.base))
        self.assertEqual(factory.port, 12342)
        self.assertEqual(factory.debugger_address, 'localhost:12342')

    def test_bound_port_before_launch_retries_once(self):
        with patch('direct_apply._free_port', side_effect=[12341, 12342]), \
             patch('direct_apply._port_is_bound', side_effect=[True, False]), \
             patch('selenium.webdriver.Chrome', return_value=self.driver(12342)) as chrome:
            factory = browser_factory(self.base)
            factory()
        self.assertEqual(factory.port, 12342)
        self.assertEqual(chrome.call_count, 1)

    def test_repeated_collision_is_bounded(self):
        with patch('direct_apply._free_port', side_effect=[12341, 12342]) as allocate, \
             patch('direct_apply._port_is_bound', return_value=True), \
             patch('selenium.webdriver.Chrome') as chrome:
            with self.assertRaises(OSError):
                browser_factory(self.base)()
        self.assertEqual(allocate.call_count, 2)
        chrome.assert_not_called()

    def test_explicit_collision_during_launch_retries(self):
        with patch('direct_apply._free_port', side_effect=[12341, 12342]), \
             patch('direct_apply._port_is_bound', side_effect=[False, True, False]), \
             patch('selenium.webdriver.Chrome', side_effect=[WebDriverException('address already in use'), self.driver(12342)]) as chrome:
            browser_factory(self.base)()
        self.assertEqual(chrome.call_count, 2)

    def test_other_startup_failure_does_not_retry(self):
        with patch('direct_apply._free_port', return_value=12341), \
             patch('direct_apply._port_is_bound', return_value=False), \
             patch('selenium.webdriver.Chrome', side_effect=WebDriverException('profile in use')) as chrome:
            with self.assertRaises(WebDriverException):
                browser_factory(self.base)()
        self.assertEqual(chrome.call_count, 1)

    def test_attach_does_not_allocate_port_or_create_profile(self):
        with patch('direct_apply._free_port') as allocate, \
             patch('selenium.webdriver.Chrome', return_value=self.driver(12341)) as chrome:
            browser_factory(self.base, debugger_address='localhost:12341')()
        allocate.assert_not_called()
        self.assertFalse(self.base.exists())
        options = chrome.call_args.kwargs['options']
        self.assertEqual(options.debugger_address, 'localhost:12341')
        self.assertEqual(options.arguments, [])
