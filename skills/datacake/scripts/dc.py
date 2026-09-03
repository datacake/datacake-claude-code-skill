#!/usr/bin/env python3
"""Run a GraphQL operation against the Datacake API and print the JSON response.

Usage:
  python3 scripts/dc.py 'query { user { id email } }'
  python3 scripts/dc.py --file query.graphql --vars '{"workspaceId": "..."}'
  cat query.graphql | python3 scripts/dc.py -
  python3 scripts/dc.py --login you@example.com      # prompts for the password, prints an access token

Token lookup order: --token, $DATACAKE_TOKEN, ~/.datacake/token (a file holding only the token).
Exit codes: 0 ok, 1 GraphQL errors (printed to stderr with extensions.code), 2 HTTP/network/usage error.
Standard library only.
"""
import argparse
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = "https://api.datacake.co/graphql/"
# History queries over long ranges can take a while; 60 s avoids false timeouts.
TIMEOUT = 60
# Retry only transient failures (network errors, 5xx). Most resolve by the second attempt.
MAX_RETRIES = 3
TOKEN_FILE = os.path.expanduser("~/.datacake/token")

LOGIN_MUTATION = """
mutation Login($email: String!, $password: String!, $otp: String) {
  login(email: $email, password: $password, otpToken: $otp) { ok token error }
}
"""


def resolve_token(explicit=None):
    if explicit:
        return explicit
    if os.environ.get("DATACAKE_TOKEN"):
        return os.environ["DATACAKE_TOKEN"]
    if os.path.exists(TOKEN_FILE):
        return open(TOKEN_FILE, encoding="utf-8").read().strip()
    return None


def gql(query, variables=None, token=None, endpoint=ENDPOINT, timeout=TIMEOUT):
    """POST one operation. Returns the parsed response dict (may contain 'errors')."""
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    headers = {"Content-Type": "application/json", "User-Agent": "datacake-skill/dc.py"}
    if token:
        headers["Authorization"] = "Token " + token
    body = json.dumps(payload).encode()
    last_error = None
    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(endpoint, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"), strict=False)
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")[:2000]
            if exc.code >= 500 and attempt + 1 < MAX_RETRIES:
                last_error = "HTTP %s: %s" % (exc.code, text)
            else:
                hint = " (token rejected: invalid or revoked)" if exc.code == 401 else " (invalid document? validate against reference/schema.graphql)" if exc.code == 400 else ""
                sys.stderr.write("HTTP %s from %s%s\n%s\n" % (exc.code, endpoint, hint, text))
                sys.exit(2)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = "network error: %s" % exc
        time.sleep(2 ** attempt)  # 1 s, 2 s, 4 s back-off
    sys.stderr.write("giving up after %d attempts: %s\n" % (MAX_RETRIES, last_error))
    sys.exit(2)


def report_errors(response):
    for err in response.get("errors") or []:
        code = (err.get("extensions") or {}).get("code", "")
        path = ".".join(str(p) for p in err.get("path") or [])
        sys.stderr.write("GraphQL error%s%s: %s\n" % (
            " [%s]" % code if code else "", " at %s" % path if path else "", err.get("message")))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?", help="GraphQL document, or '-' to read it from stdin")
    ap.add_argument("--file", "-f", help="read the GraphQL document from this file")
    ap.add_argument("--vars", "-v", help="variables as a JSON object")
    ap.add_argument("--token", help="access token (default: $DATACAKE_TOKEN, then ~/.datacake/token)")
    ap.add_argument("--endpoint", default=ENDPOINT)
    ap.add_argument("--timeout", type=int, default=TIMEOUT)
    ap.add_argument("--raw", action="store_true", help="print the response compactly instead of pretty JSON")
    ap.add_argument("--data-only", action="store_true", help="print only the 'data' object")
    ap.add_argument("--login", metavar="EMAIL", help="obtain an access token with email + password")
    args = ap.parse_args()

    if args.login:
        password = getpass.getpass("Datacake password for %s: " % args.login)
        otp = getpass.getpass("OTP code (leave empty if 2FA is off): ") or None
        resp = gql(LOGIN_MUTATION, {"email": args.login, "password": password, "otp": otp},
                   endpoint=args.endpoint, timeout=args.timeout)
        report_errors(resp)
        login = (resp.get("data") or {}).get("login") or {}
        if login.get("ok") and login.get("token"):
            print(login["token"])
            sys.stderr.write("Store it: export DATACAKE_TOKEN=<token>  (or write it to ~/.datacake/token)\n")
            return
        sys.stderr.write("login failed: %s\n" % (login.get("error") or json.dumps(resp)[:500]))
        sys.exit(1)

    if args.file:
        query = open(args.file, encoding="utf-8").read()
    elif args.query == "-" or (args.query is None and not sys.stdin.isatty()):
        query = sys.stdin.read()
    elif args.query:
        query = args.query
    else:
        ap.error("provide a query argument, --file, or pipe the query on stdin")

    variables = None
    if args.vars:
        try:
            variables = json.loads(args.vars)
        except json.JSONDecodeError as exc:
            ap.error("--vars is not valid JSON: %s" % exc)

    token = resolve_token(args.token)
    if not token:
        sys.stderr.write("warning: no token (set DATACAKE_TOKEN); request is sent unauthenticated\n")
    resp = gql(query, variables, token, args.endpoint, args.timeout)
    report_errors(resp)
    out = resp.get("data") if args.data_only else resp
    print(json.dumps(out) if args.raw else json.dumps(out, indent=2, ensure_ascii=False))
    if resp.get("errors"):
        sys.exit(1)


if __name__ == "__main__":
    main()
