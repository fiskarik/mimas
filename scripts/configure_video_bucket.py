"""Apply private-bucket CORS and 30-day retention for MIMAS video.

Run once for each production/development bucket. No keys are printed. Passing
--apply is required because this changes cloud bucket configuration.
"""
import argparse
import os
from urllib.parse import quote
from uuid import uuid4

import httpx


def configuration(origin: str):
    if not origin.startswith('https://'):
        raise ValueError('Browser origin must use HTTPS')
    return {
        'cors': {'CORSRules': [{
            'AllowedMethods': ['GET', 'PUT'], 'AllowedOrigins': [origin.rstrip('/')],
            'AllowedHeaders': ['*'], 'ExposeHeaders': ['ETag'], 'MaxAgeSeconds': 300,
        }]},
        'lifecycle': {'Rules': [{
            'ID': 'mimas-recordings-30-days', 'Status': 'Enabled',
            'Filter': {'Prefix': 'recordings/'}, 'Expiration': {'Days': 30},
            'AbortIncompleteMultipartUpload': {'DaysAfterInitiation': 1},
        }]},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--origin', required=True, help='Exact public MIMAS origin, e.g. https://mimas.onrender.com')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    rules = configuration(args.origin)
    if not args.apply:
        print('Dry run: CORS permits signed GET/PUT from', args.origin.rstrip('/'))
        print('Lifecycle deletes recordings/ after 30 days and aborts incomplete multipart uploads after one day.')
        print('Pass --apply to configure the bucket. Use a separate bucket for development.')
        return
    from backend.media import _client, _bucket
    client, bucket = _client(), _bucket()
    versioning = client.get_bucket_versioning(Bucket=bucket).get('Status')
    if versioning:
        raise RuntimeError('Use a new bucket with versioning disabled for 30-day video retention')
    # Check actual anonymous access against an object created with the same
    # private default ACL as interview recordings. A public bucket policy
    # would otherwise bypass every short-lived playback URL.
    probe_key = 'recordings/_privacy-check/' + uuid4().hex
    client.put_object(Bucket=bucket, Key=probe_key, Body=b'mimas-private-check')
    try:
        endpoint = os.getenv('MIMAS_S3_ENDPOINT', 'https://storage.yandexcloud.net').rstrip('/')
        url = endpoint + '/' + quote(bucket, safe='') + '/' + quote(probe_key, safe='/')
        try:
            response = httpx.get(url, follow_redirects=False, timeout=15)
        except httpx.HTTPError as exc:
            raise RuntimeError('Cannot verify anonymous bucket access') from exc
        if response.status_code != 403:
            raise RuntimeError('Bucket privacy check failed: anonymous GET did not return 403')
    finally:
        client.delete_object(Bucket=bucket, Key=probe_key)
    client.put_bucket_cors(Bucket=bucket, CORSConfiguration=rules['cors'])
    client.put_bucket_lifecycle_configuration(Bucket=bucket, LifecycleConfiguration=rules['lifecycle'])
    # Verify the provider accepted the rules before telling an operator to publish.
    stored_cors = client.get_bucket_cors(Bucket=bucket)
    stored_lifecycle = client.get_bucket_lifecycle_configuration(Bucket=bucket)
    if not any('ETag' in rule.get('ExposeHeaders', []) for rule in stored_cors.get('CORSRules', [])):
        raise RuntimeError('Bucket CORS did not expose ETag')
    if not any(rule.get('ID') == 'mimas-recordings-30-days' and
               rule.get('Status') == 'Enabled' for rule in stored_lifecycle.get('Rules', [])):
        raise RuntimeError('Bucket retention rule was not persisted')
    print('Configured and verified video bucket CORS/lifecycle for', args.origin.rstrip('/'))


if __name__ == '__main__':
    main()
