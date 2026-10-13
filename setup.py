from setuptools import setup, find_packages
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))

APP = ['JobRobo.py']

OPTIONS = {
    'argv_emulation': False,
    'packages': [
        'tkinter', 'selenium', 'openai', 'pyautogui', 'pdfplumber', 'undetected_chromedriver',
        'dotenv', 'modules'
    ],
    'includes': [
        'runAiBot', 'modules.open_chrome', 'modules.config_loader'
    ],
    'excludes': [
        'tqdm.tk', 'rubicon', 'typing_extensions', 'pypdfium2_raw',
        'IPython', 'jupyter', 'mouseinfo', 'standalone', 'backports',
        'backports.tarfile', 'notebook', '.env'
    ],
    'iconfile': 'assets/jobrobo.icns',
    'resources': [
        'assets',
        ('config', ['config/resume_optimizer_defaults.json']),
        ('config/skills', ['config/skills/Skills_Keyword_Bank_Staff_Principal_2026-10.md']),
        ('config/bullets', [
            'config/bullets/Trek_Health_Bullet_Bank.md',
            'config/bullets/Codex_SelfHosted_Bullet_Bank.md',
            'config/bullets/Sohamhamso_Bullet_Bank.md',
            'config/bullets/SponsorSkip_Bullet_Bank.md',
        ]),
    ]
}

setup(
    app=APP,
    data_files=[],
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
    packages=find_packages(),
)
