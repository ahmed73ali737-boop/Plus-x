"""Container readiness probe using only the Python standard library.

No credentials or response bodies are emitted. This is a readiness check, not a
production-acceptance override. Liveness remains /api/health/live.
"""
import json
import sys
import urllib.error
import urllib.request


def main():
    try:
        with urllib.request.urlopen('http://127.0.0.1:4310/api/health/ready', timeout=4) as response:
            data=json.load(response)
            if response.status!=200 or data.get('status')!='ready':
                print('APP_NOT_READY', file=sys.stderr)
                return 1
    except (OSError, ValueError, urllib.error.URLError):
        print('APP_READINESS_UNAVAILABLE', file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
