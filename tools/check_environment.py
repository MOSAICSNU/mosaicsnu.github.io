"""Exit nonzero when this source version needs installation in the venv."""

from importlib.metadata import version
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def main():
    if sys.version_info < (3, 10):
        return 1
    try:
        from mosaic import __version__
        import nd2, numpy, PySide6, pyqtgraph, scipy  # noqa: F401
        if version('mosaic') != __version__:
            return 1
    except Exception as exc:
        # No traceback on first launch; the launcher will run pip install.
        print(f'Environment requires installation: {exc}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
