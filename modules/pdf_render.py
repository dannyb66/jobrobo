"""Bounded, crash-contained PDF previews. Native PDFium runs only in children."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

_RENDER_SLOTS = threading.BoundedSemaphore(4)
_WORKER_SCRIPT = Path(__file__).resolve()
_RENDER_VERSION = 1


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _versions():
    result = {}
    for name in ('pdfplumber', 'pypdfium2'):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = 'unavailable'
    return result


def _console(message):
    print(message, flush=True)


def render_page_images(root, *, dpi=120, timeout=180, log=_console):
    """Render a job's PDF pair in a fresh interpreter; preview failures are data.

    Slot waiting does not consume the execution timeout. Cache validation uses
    input/output bytes so incomplete or stale previews are never reused.
    """
    root = Path(root).resolve()
    if dpi <= 0 or timeout <= 0:
        raise ValueError('PDF render DPI and timeout must be positive')
    started = time.monotonic()
    versions = _versions()
    result = {'status': 'unavailable', 'renderer': 'pdfplumber/PDFium subprocess',
              'versions': versions, 'dpi': dpi, 'pages': 0, 'cache_hit': False}

    def message(text):
        if log:
            try:
                log(f'[PDF preview {root.name}] {text}')
            except Exception:
                pass

    try:
        inputs = {name + '.pdf': _sha(root/(name+'.pdf'))
                  for name in ('original', 'optimized') if (root/(name+'.pdf')).is_file()}
        if not inputs:
            raise ValueError('No resume PDFs available for preview')
        key = {'inputs': inputs, 'dpi': dpi, 'versions': versions, 'render_version': _RENDER_VERSION}
        cache_path = root/'pdf-preview-cache.json'
        try:
            cache = json.loads(cache_path.read_text())
            if not isinstance(cache, dict):
                raise ValueError('Invalid preview cache')
            images = cache.get('images', {})
            if not isinstance(images, dict):
                raise ValueError('Invalid preview image cache')
            if (cache.get('key') == key and images
                    and all(Path(name).name == name and name.endswith('.png')
                            and _sha(root/name) == digest for name, digest in images.items())):
                result.update(status='complete', pages=len(images), cache_hit=True)
                return result
        except (OSError, ValueError, TypeError):
            pass
        # A failed replacement must not leave previews of older PDF bytes.
        cache_path.unlink(missing_ok=True)
        for old in root.glob('*-page-*.png'):
            old.unlink()
        message('Waiting for renderer slot (maximum 4 children)')
        with _RENDER_SLOTS:
            message('Rendering preview images in an isolated process')
            with tempfile.TemporaryDirectory(dir=root, prefix='.pdf-preview-') as output:
                command = [sys.executable, str(_WORKER_SCRIPT), '--root', str(root),
                           '--output', output, '--dpi', str(dpi)]
                completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
                result['returncode'] = completed.returncode
                if completed.returncode != 0:
                    result['error_kind'] = 'child_signal' if completed.returncode < 0 else 'child_failed'
                    return result
                payload = json.loads(completed.stdout)
                names = payload['images']
                if not isinstance(names, list) or not names or len(set(names)) != len(names):
                    raise ValueError('Invalid renderer image inventory')
                from PIL import Image
                images = {}
                for name in names:
                    if not isinstance(name, str) or Path(name).name != name or not name.endswith('.png'):
                        raise ValueError('Invalid renderer image path')
                    path = Path(output)/name
                    with Image.open(path) as image:
                        image.verify()
                    images[name] = _sha(path)
                if any(_sha(root/name) != digest for name, digest in inputs.items()):
                    raise ValueError('PDF changed while rendering previews')
                # Only publish validated files, then atomically commit the cache.
                cache_path.unlink(missing_ok=True)
                for old in root.glob('*-page-*.png'):
                    old.unlink()
                for name in names:
                    os.replace(Path(output)/name, root/name)
                temporary = Path(output)/'cache.json'
                temporary.write_text(json.dumps({'key': key, 'images': images}, sort_keys=True)+'\n')
                os.replace(temporary, cache_path)
                result.update(status='complete', pages=len(names), pid=payload.get('pid'))
    except subprocess.TimeoutExpired:
        result['error_kind'] = 'timeout'
    except (OSError, ValueError, KeyError, TypeError) as error:
        result['error_kind'] = type(error).__name__
    finally:
        if result['status'] != 'complete':
            # In particular, do not expose a partially published image pair.
            try:
                (root/'pdf-preview-cache.json').unlink(missing_ok=True)
                for old in root.glob('*-page-*.png'):
                    old.unlink()
            except OSError:
                pass
        result['elapsed_seconds'] = round(time.monotonic()-started, 3)
        message(f"Preview {result['status']}; {result['pages']} pages; {result['elapsed_seconds']:.2f}s")
    return result


def _main():
    import argparse
    import pdfplumber  # Never imported by the parent helper.
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dpi', type=int, required=True)
    args = parser.parse_args()
    names = []
    for name in ('original', 'optimized'):
        path = args.root/(name+'.pdf')
        if path.is_file():
            with pdfplumber.open(path) as document:
                for number, page in enumerate(document.pages, 1):
                    filename = f'{name}-page-{number}.png'
                    page.to_image(resolution=args.dpi).save(args.output/filename)
                    names.append(filename)
    print(json.dumps({'images': names, 'pid': os.getpid()}))


if __name__ == '__main__':
    _main()
