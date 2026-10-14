"""Explicit browser construction; importing this module has no browser side effects."""


def create_browser(*, background=None):
    import os
    from pathlib import Path
    from config import settings
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.support.ui import WebDriverWait
    from modules.helpers import find_default_profile_directory, make_directories
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
        profile = os.path.expanduser(configured) if configured else find_default_profile_directory()
        if profile:
            Path(profile).mkdir(parents=True, exist_ok=True)
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
