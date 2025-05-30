from setuptools import setup, find_packages
from dotenv import load_dotenv
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))
# print("PYTHONPATH:", sys.path)

load_dotenv()  # take environment variables from .env

APP = ['JobRobo.py']
DATA_FILES = ['.env']  # Add any files you read from
OPTIONS = {
    'argv_emulation': False,
    'packages': [
        'tkinter', 'selenium', 'openai', 'pyautogui', 'pdfplumber', 'undetected_chromedriver',
        'dotenv', 'modules'
    ],
    'includes': [
        'runAiBot', 'modules.open_chrome'  # <-- explicitly include anything py2app might miss
    ],
    'excludes': [
        'tqdm.tk', 'rubicon', 'typing_extensions', 'pypdfium2_raw',
        'IPython', 'jupyter', 'mouseinfo', 'standalone', 'backports',
        'backports.tarfile', 'notebook'
    ],
    'iconfile': 'assets/jobrobo.icns',
    'resources': ['.env', 'assets']  # optional: include other needed resources
}

setup(
    app=APP,
    data_files=[],
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
    packages=find_packages(),
)