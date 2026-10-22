"""Explicit browser construction; importing this module has no browser side effects."""


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
    if settings.disable_extensions:
        options.add_argument("--disable-extensions")
    if not settings.safe_mode:
        configured = getattr(settings, "chrome_profile_path", "").strip()
        profile = os.path.expanduser(configured or "~/.jobrobo/chrome-profile")
        if profile:
            Path(profile).mkdir(parents=True, exist_ok=True)
            check_profile_available(profile)
            options.add_argument(f"--user-data-dir={profile}")
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
