"""Real native rendering, isolated child failures, and bounded concurrency."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import signal
import subprocess
import threading
from unittest.mock import patch

from PIL import Image
from PyPDF2 import PdfWriter

from modules import pdf_render


def pdfs(root):
    root.mkdir()
    for name in ('original', 'optimized'):
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=300)
        writer.add_blank_page(width=200, height=300)
        with (root/(name+'.pdf')).open('wb') as stream:
            writer.write(stream)
    return root


def test_sixteen_bundles_use_real_children_at_most_four_and_cache(tmp_path):
    roots = [pdfs(tmp_path/str(i)) for i in range(16)]
    run = subprocess.run
    lock = threading.Lock()
    active = peak = 0

    def observe(*args, **kwargs):
        nonlocal active, peak
        assert kwargs["timeout"] == 180
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            return run(*args, **kwargs)
        finally:
            with lock:
                active -= 1

    with patch.object(pdf_render.subprocess, 'run', side_effect=observe):
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda root: pdf_render.render_page_images(root, log=None), roots))
    assert peak == 4
    assert all(result['status'] == 'complete' and result['pages'] == 4 for result in results)
    assert len({result['pid'] for result in results}) == 16
    for root in roots:
        for image in root.glob('*-page-*.png'):
            with Image.open(image) as png:
                png.verify()
    with patch.object(pdf_render.subprocess, 'run', side_effect=AssertionError('Cache should avoid rendering')):
        assert pdf_render.render_page_images(roots[0], log=None)['cache_hit']
    image = roots[0]/'optimized-page-1.png'
    image.write_bytes(b'corrupt')
    repaired = pdf_render.render_page_images(roots[0], log=None)
    assert repaired['status'] == 'complete' and not repaired['cache_hit']
    cache_path = roots[0]/'pdf-preview-cache.json'
    malformed = json.loads(cache_path.read_text())
    malformed['images'] = ['not-an-image-map']
    cache_path.write_text(json.dumps(malformed))
    messages = []
    assert pdf_render.render_page_images(roots[0], log=messages.append)['status'] == 'complete'
    assert any('isolated process' in message for message in messages)


def test_child_signal_cannot_kill_parent_or_publish_partial_previews(tmp_path):
    root = pdfs(tmp_path/'signal')
    worker = tmp_path/'crash.py'
    worker.write_text('import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n')
    with patch.object(pdf_render, '_WORKER_SCRIPT', worker):
        result = pdf_render.render_page_images(root, log=None)
    assert result['status'] == 'unavailable'
    assert result['error_kind'] == 'child_signal'
    assert result['returncode'] == -signal.SIGKILL
    assert not list(root.glob('*-page-*.png'))
    assert not list(root.glob('.pdf-preview-*'))
    # Same process and semaphore continue functioning after a native-style exit.
    assert pdf_render.render_page_images(root, log=None)['status'] == 'complete'


def test_timeout_kills_child_releases_slot_and_removes_stale_images(tmp_path):
    root = pdfs(tmp_path/'timeout')
    (root/'optimized-page-1.png').write_bytes(b'stale')
    worker = tmp_path/'sleep.py'
    worker.write_text('import time\ntime.sleep(10)\n')
    with patch.object(pdf_render, '_WORKER_SCRIPT', worker):
        result = pdf_render.render_page_images(root, timeout=.1, log=None)
    assert result['error_kind'] == 'timeout'
    assert not list(root.glob('*-page-*.png'))
    assert not list(root.glob('.pdf-preview-*'))
    assert pdf_render.render_page_images(root, log=None)['status'] == 'complete'


def test_malformed_child_inventory_is_contained(tmp_path):
    root = pdfs(tmp_path/'malformed')
    worker = tmp_path/'malformed.py'
    worker.write_text('print(\'{"images":["../untrusted.png"]}\')\n')
    with patch.object(pdf_render, '_WORKER_SCRIPT', worker):
        result = pdf_render.render_page_images(root, log=None)
    assert result['status'] == 'unavailable'
    assert not (root/'pdf-preview-cache.json').exists()


def test_worker_import_does_not_load_native_pdfium_in_parent():
    code = 'import sys; from modules import pdf_render; print("pypdfium2" in sys.modules)'
    result = subprocess.run([__import__('sys').executable, '-c', code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'False'
