# [MEDIUM] Open redirect after staff login through a tab in `next`

**Severity**: Medium
**Confidence**: High
**Category**: Open Redirect

**Affected locations**:
- `server/hallmonitor.py:256` — `next` check tests only the raw string's first two characters
- `server/hallmonitor.py:267` — `redirect(next_url)` emits the normalized value
- `server/pages.py:429` — `next` from the query string is carried into the form unchanged

**Preconditions**: Unauthenticated attacker. The victim is a staff member who follows a link and
enters the shared staff password.

### Description

The login handler accepts a `next` path and follows it after a correct password. It rejects values
that do not start with `/` or that start with `//`. A value of `/<TAB>/evil.example` passes both
tests. Werkzeug drops the tab when it builds the `Location` header, so the response redirects to
`//evil.example`, which browsers treat as a scheme-relative URL on another host. Browsers also strip
tabs and newlines from URLs themselves, so the redirect leaves the site either way.

The `next` value arrives through the query string on `GET /login`, is written into a hidden form
field (escaping does not touch the tab), and is posted back when the staff member signs in.

### Vulnerable Code

```python
# server/hallmonitor.py:254-267
@app.post("/login")
def login():
    next_url = request.form.get("next", "/")
    # Only follow local paths, so the login form cannot bounce a staff member to another site.
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"
    ...
    session["staff"] = fingerprint(password_hash)
    return redirect(next_url)
```

```python
# server/pages.py:429
<input type="hidden" name="next" value="{escape(next_url)}" />
```

### Impact

An attacker controls where a staff member lands immediately after typing the shared staff password
on the real hallmonitor site. A landing page that imitates the hallmonitor login ("Your session
expired, sign in again") collects the shared password, which grants access to every room's data
and remains valid until an administrator changes it. The genuine domain in the link and the
genuine login page make the lure credible.

### Attack Scenario

1. The attacker sends staff a link:
   `https://hallmonitor.willhackforsushi.com/login?next=/%09/evil.example/relogin`
2. The staff member sees the real login page and signs in.
3. The server answers `302 Location: //evil.example/relogin`, and the browser loads
   `https://evil.example/relogin`.
4. The attacker's page imitates the hallmonitor login and records the password the staff member
   enters.

### Validation

Run against the local copy described in `recon.md`. The script follows the link flow: it fetches
the login page with the crafted `next`, reads the hidden field, and posts it with the password.

```bash
uv run 01-medium-open-redirect-login.py
```

Observed output:

```
hidden next field: '/\t/evil.example'
POST /login -> 302 Location: //evil.example
```

A one-line check without the page fetch:

```bash
curl -s -o /dev/null -w '%{http_code} %header{location}\n' \
  --data-urlencode $'next=/\t/evil.example' --data-urlencode password=testpass123 \
  http://127.0.0.1:18504/login
# 302 //evil.example
```

### References

- CWE-601: URL Redirection to Untrusted Site ('Open Redirect')
