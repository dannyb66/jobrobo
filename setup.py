from setuptools import setup, find_packages
from dotenv import load_dotenv
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))

load_dotenv()  # take environment variables from .env

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
        ('config', ['config/resume_optimizer_defaults.json'])  # ✅ Explicitly include only this file
    ]
}

setup(
    app=APP,
    data_files=[],
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
    packages=find_packages(),
)