import json
from pathlib import Path
import tempfile
import unittest

from mosaic.session import find_session_movie, source_fingerprint, validate_session, write_session


class SessionTests(unittest.TestCase):
    def test_relocated_source_and_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            movie = root / 'recording.nd2'
            movie.write_bytes(b'example recording')
            data = {'movie_path': r'C:\old\recording.nd2',
                    'source_identity': source_fingerprint(movie)}
            session = root / 'recording_ana' / 'analysis_info.json'
            self.assertEqual(find_session_movie(data, session), movie)
            movie.write_bytes(b'wrong recording')
            self.assertIsNone(find_session_movie(data, session))

    def test_schema_validation(self):
        validate_session({'version': 1, 'entries': []})
        validate_session({'version': 2, 'entries': []})
        for data in ([], {'version': 99, 'entries': []}, {'entries': 'wrong'}):
            with self.assertRaises(ValueError):
                validate_session(data)

    def test_failed_json_write_preserves_previous_session(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'analysis_info.json'
            write_session(path, {'entries': []})
            with self.assertRaises(ValueError):
                write_session(path, {'value': float('nan')})
            self.assertEqual(json.loads(path.read_text()), {'entries': []})

