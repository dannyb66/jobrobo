"""Explicit browser construction; importing this module has no browser side effects.

The debug port exists only so the CAPTCHA solver can attach over CDP.
"""

class ChromeProfileInUse(RuntimeError):
    """A live Chrome process already owns the configured user-data directory."""


def check_profile_available(profile):
    import os
    import socket
    from pathlib import Path
    lock = Path(profile) / 'SingletonLock'
    if not lock.is_symlink():
        return
    try:
        hostname, value = os.readlink(lock).rsplit('-', 1)
        pid = int(value)
    except (OSError, ValueError):
        return  # Chrome diagnoses other lock formats itself.
    local_hosts = {socket.gethostname(), socket.getfqdn()}
    if hostname not in local_hosts or pid <= 1:
        return
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return  # Leave stale-lock recovery to Chrome.
    except PermissionError:
        pass  # The process exists, but belongs to a different user.
    raise ChromeProfileInUse(
        f'JobRobo Chrome profile is already open (PID {pid}): {profile}. '
        'Close the Chrome window using this dedicated profile, then retry. '
        'No profile files were deleted.'
    )


def _free_port():
    import socket
    try:
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]
        finally:
            sock.close()
    except OSError:
        return 9222


def _cdp_flags(options):
    import os
    if os.getenv("JOBROBO_DISABLE_CDP"):
        return []
    # `arguments` can be a non-list (a mock, or a future options object), so use
    # the iterable form only when the attribute really is one.
    existing = getattr(options, "arguments", None)
    if isinstance(existing, (list, tuple)) and any(
            str(arg).startswith("--remote-debugging-port") for arg in existing):
        return []
    return [f"--remote-debugging-port={_free_port()}", "--remote-debugging-address=127.0.0.1"]


# A session that looks like a real desktop: fixed window, matching locale and
# timezone, and no automation switch left on. reCAPTCHA Enterprise scores are
# depressed by headless and by framework artefacts such as the CDP
# `Runtime.enable` tell, and by a locale/timezone that disagrees.
_PERSONA_FLAGS = (
    "--window-size=1280,900",
    "--lang=en-US",
)


def create_browser(*, background=None):
    import os
    import importlib
    from pathlib import Path
    settings = importlib.import_module("config.settings")
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
    from modules.helpers import make_directories
    from config.questions import default_resume_path

    make_directories([settings.file_name, settings.failed_file_name, settings.logs_folder_path + "/screenshots",
                      default_resume_path, settings.generated_resume_path + "/temp"])

    if settings.stealth_mode:
        import undetected_chromedriver as uc
        options = uc.ChromeOptions()
    else:
        from selenium import webdriver
        options = webdriver.ChromeOptions()
    in_background = settings.run_in_background if background is None else background
    if in_background:
        options.add_argument("--headless=new")
    options.arguments.extend(_PERSONA_FLAGS)
    if settings.disable_extensions:
        options.add_argument("--disable-extensions")
    if not settings.safe_mode:
        configured = getattr(settings, "chrome_profile_path", "").strip()
        profile = os.path.expanduser(configured or "~/.jobrobo/chrome-profile")
        if profile:
            Path(profile).mkdir(parents=True, exist_ok=True)
            check_profile_available(profile)
            options.add_argument(f"--user-data-dir={profile}")
    options.arguments.extend(_cdp_flags(options))
    browser = uc.Chrome(options=options) if settings.stealth_mode else webdriver.Chrome(options=options)
    try:
        browser.maximize_window()
        return browser, WebDriverWait(browser, 5), ActionChains(browser)
    except BaseException:
        try:
            browser.quit()
        except Exception:
            pass
        raise
