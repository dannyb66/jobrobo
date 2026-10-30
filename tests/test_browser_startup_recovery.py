"""Profile ownership and credential fallback regressions; no browser/network."""
import contextlib
import ast
import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from modules.open_chrome import ChromeProfileInUse, check_profile_available
from modules.ai import openai_key_loader as keys


class StartupRecoveryTest(unittest.TestCase):
    def bot_namespace(self, main, prepare_only=False):
        source=Path(__file__).resolve().parents[1]/'runAiBot.py'
        node=next(n for n in ast.parse(source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='run_bot')
        browser=Mock()
        namespace={'main':main,'driver':browser,'wait':object(),'actions':object(),
                   '_browser_background':False,'prepare_only_run':prepare_only}
        exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),namespace)
        return namespace,browser

    def test_normal_run_releases_profile_and_clears_browser_state(self):
        namespace,browser=self.bot_namespace(Mock())
        namespace['run_bot']()
        browser.quit.assert_called_once_with()
        self.assertIsNone(namespace['driver'])
        self.assertIsNone(namespace['wait'])
        self.assertIsNone(namespace['actions'])

    def test_failed_run_also_releases_its_browser(self):
        namespace,browser=self.bot_namespace(Mock(side_effect=RuntimeError('fixture failure')))
        with self.assertRaisesRegex(RuntimeError,'fixture failure'):namespace['run_bot']()
        browser.quit.assert_called_once_with()
        self.assertIsNone(namespace['driver'])

    def test_prepare_only_keeps_the_review_window(self):
        namespace,browser=self.bot_namespace(Mock(),prepare_only=True)
        namespace['run_bot']()
        browser.quit.assert_not_called()
        self.assertIs(namespace['driver'],browser)

    def test_live_local_profile_owner_is_reported_without_deleting_lock(self):
        with TemporaryDirectory() as tmp:
            lock=Path(tmp)/'SingletonLock';lock.symlink_to('local-test-12345')
            with patch('socket.gethostname',return_value='local-test'), patch('socket.getfqdn',return_value='local-test'), patch('os.kill') as probe:
                with self.assertRaisesRegex(ChromeProfileInUse,'already open.*12345'):
                    check_profile_available(tmp)
            probe.assert_called_once_with(12345,0)
            self.assertTrue(lock.is_symlink())

    def test_dead_owner_is_left_for_chromes_stale_lock_recovery(self):
        with TemporaryDirectory() as tmp:
            lock=Path(tmp)/'SingletonLock';lock.symlink_to('local-test-12345')
            with patch('socket.gethostname',return_value='local-test'), patch('socket.getfqdn',return_value='local-test'), patch('os.kill',side_effect=ProcessLookupError):
                check_profile_available(tmp)
            self.assertTrue(lock.is_symlink())

    def test_remote_or_malformed_locks_are_not_treated_as_local_processes(self):
        with TemporaryDirectory() as tmp:
            lock=Path(tmp)/'SingletonLock'
            for target in ('different-host-12345','bad-format'):
                lock.symlink_to(target)
                with patch('socket.gethostname',return_value='local-test'), patch('socket.getfqdn',return_value='local-test'), patch('os.kill') as probe:
                    check_profile_available(tmp)
                probe.assert_not_called();lock.unlink()

    def test_environment_key_never_calls_dotenv_or_cloud(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'unit-test-value'}), patch.object(keys,'load_dotenv') as dotenv, patch.object(keys.requests,'get') as get, contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(keys.load_openai_key())
        dotenv.assert_not_called();get.assert_not_called()

    def test_local_dotenv_key_prevents_cloud_request(self):
        def local(**kwargs):os.environ['OPENAI_API_KEY']='unit-test-value'
        with patch.dict(os.environ,{},clear=True), patch.object(keys,'load_dotenv',side_effect=local) as dotenv, patch.object(keys.requests,'get') as get, contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(keys.load_openai_key())
        dotenv.assert_called_once_with(override=False);get.assert_not_called()

    def test_cloud_still_works_when_no_local_key_exists(self):
        result=Mock(status_code=200);result.json.return_value={'openai_key':'unit-test-cloud'}
        with patch.dict(os.environ,{},clear=True), patch.object(keys,'load_dotenv'), patch.object(keys.requests,'get',return_value=result), contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(keys.load_openai_key())
            self.assertEqual(os.environ['OPENAI_API_KEY'],'unit-test-cloud')

    def test_failed_cloud_does_not_print_response_body_or_claim_local_success(self):
        result=Mock(status_code=500,text='private server body')
        output=io.StringIO()
        with patch.dict(os.environ,{},clear=True), patch.object(keys,'load_dotenv'), patch.object(keys.requests,'get',return_value=result), contextlib.redirect_stdout(output):
            self.assertFalse(keys.load_openai_key())
        self.assertNotIn('private server body',output.getvalue())
        self.assertNotIn('Loaded OPENAI_API_KEY',output.getvalue())


if __name__=='__main__':unittest.main()
