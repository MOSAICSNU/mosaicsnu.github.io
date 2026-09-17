"""Versioned session metadata and portable source-file lookup."""

import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import tempfile


def source_fingerprint(path):
    """Hash size and first/last MiB; a relocation check, not a full-file hash."""
    path = Path(path)
    size = path.stat().st_size
    digest = hashlib.sha256(str(size).encode('ascii'))
    with path.open('rb') as stream:
        digest.update(stream.read(1024 * 1024))
        stream.seek(max(0, size - 1024 * 1024))
        digest.update(stream.read(1024 * 1024))
    return {'size_bytes': size, 'sample_sha256': digest.hexdigest()}


def source_matches(path, identity):
    if not Path(path).is_file():
        return False
    if not identity:
        return True  # Legacy files contain no identity information.
    return source_fingerprint(path) == identity


def find_session_movie(data, session_path):
    stored = str(data.get('movie_path', ''))
    identity = data.get('source_identity')
    candidates = [Path(stored)] if stored else []
    relative = data.get('movie_relative_path')
    if relative:
        candidates.append(Path(session_path).parent / str(relative))
    # Recognize a Windows filename even when the session is opened on macOS.
    name = PureWindowsPath(stored).name if '\\' in stored else Path(stored).name
    if name:
        candidates.extend([Path(session_path).parent / name, Path(session_path).parent.parent / name])
    for candidate in candidates:
        if source_matches(candidate, identity):
            return candidate
    return None


def validate_session(data):
    if not isinstance(data, dict) or data.get('version', 1) not in (1, 2):
        raise ValueError('Unsupported analysis session format. Expected schema version 1 or 2.')
    if not isinstance(data.get('entries'), list):
        raise ValueError('The session must contain a list of saved ROI entries.')
    if not isinstance(data.get('saved_decay_percents', [10, 50, 90]), list):
        raise ValueError('Invalid saved decay levels.')
    if any(not isinstance(entry, dict) for entry in data['entries']):
        raise ValueError('Invalid saved ROI entry.')


def write_session(path, data):
    """Replace JSON only after a complete, valid UTF-8 write succeeds."""
    path = Path(path)
    text = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix=path.name + '.', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
