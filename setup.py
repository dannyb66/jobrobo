from setuptools import setup
from dotenv import load_dotenv

APP = ['JobRobo.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': False,
    'packages': ['tkinter', 'selenium', 'openai', 'pyautogui', 'pdfplumber', 'undetected_chromedriver'],
    'includes': [],
    'excludes': ['tqdm.tk', 'rubicon', 'typing_extensions', 'pypdfium2_raw', 'IPython', 'jupyter', 'mouseinfo', 'standalone', 'backports', 'backports.tarfile', 'notebook'],
    'iconfile': 'assets/jobrobo.icns'
}

load_dotenv()  # take environment variables from .env.

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)