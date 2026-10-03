"""Bucket setup must fail closed before enabling public-facing recording links."""
import sys
from types import SimpleNamespace

import pytest

from scripts import configure_video_bucket as setup


class FakeBucket:
    def __init__(self, versioning=None):
        self.versioning = versioning
        self.calls = []
    def get_bucket_versioning(self, **kwargs):
        return {'Status': self.versioning} if self.versioning else {}
    def put_object(self, **kwargs):
        self.calls.append('probe')
    def delete_object(self, **kwargs):
        self.calls.append('delete')
    def put_bucket_cors(self, **kwargs):
        self.calls.append('cors')
    def put_bucket_lifecycle_configuration(self, **kwargs):
        self.calls.append('lifecycle')
    def get_bucket_cors(self, **kwargs):
        return setup.configuration('https://mimas.example')['cors']
    def get_bucket_lifecycle_configuration(self, **kwargs):
        return setup.configuration('https://mimas.example')['lifecycle']


def test_bucket_rejects_versioning_and_public_reads(monkeypatch):
    from backend import media
    monkeypatch.setattr(media, '_bucket', lambda: 'test-bucket')
    monkeypatch.setattr(sys, 'argv', ['configure_video_bucket.py', '--origin',
                                     'https://mimas.example', '--apply'])
    versioned = FakeBucket('Enabled')
    monkeypatch.setattr(media, '_client', lambda: versioned)
    with pytest.raises(RuntimeError, match='versioning'):
        setup.main()
    assert not versioned.calls

    public = FakeBucket()
    monkeypatch.setattr(media, '_client', lambda: public)
    monkeypatch.setattr(setup.httpx, 'get', lambda *args, **kwargs: SimpleNamespace(status_code=200))
    with pytest.raises(RuntimeError, match='privacy'):
        setup.main()
    assert public.calls == ['probe', 'delete']


def test_private_bucket_gets_cors_and_retention(monkeypatch):
    from backend import media
    monkeypatch.setattr(media, '_bucket', lambda: 'test-bucket')
    bucket = FakeBucket()
    monkeypatch.setattr(media, '_client', lambda: bucket)
    monkeypatch.setattr(setup.httpx, 'get', lambda *args, **kwargs: SimpleNamespace(status_code=403))
    monkeypatch.setattr(sys, 'argv', ['configure_video_bucket.py', '--origin',
                                     'https://mimas.example', '--apply'])
    setup.main()
    assert bucket.calls == ['probe', 'delete', 'cors', 'lifecycle']
