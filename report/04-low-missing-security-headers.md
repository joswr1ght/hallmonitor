# [LOW] No browser security headers on the staff pages

**Severity**: Low
**Confidence**: High
**Category**: Missing Security Headers

**Affected locations**:
- `server/hallmonitor.py:132` — `create_app` sets no response headers
- `server/pages.py:404` — `page()` emits no Content Security Policy (CSP) `<meta>` either
- `server/deploy/hallmonitor.willhackforsushi.com.conf:1` — the Apache virtual host adds none

**Preconditions**: Unauthenticated attacker able to get a signed-in staff member to visit a page
the attacker controls.

### Description

Responses from the app carry no `Content-Security-Policy`, `X-Frame-Options` (or CSP
`frame-ancestors`), `X-Content-Type-Options`, or `Referrer-Policy`. The Apache virtual host in the
repository adds none. `Strict-Transport-Security` (HSTS) is also absent. The certbot-generated `-le-ssl.conf` on the
server is not in the repository, but a request to production (below) confirms Apache adds none of
these headers there either.

The staff pages have no state-changing buttons, so framing the pages exposes little today. The
missing CSP removes a second layer of protection if an escaping mistake is introduced later in the
f-string HTML in `pages.py`.

### Vulnerable Code

```python
# server/hallmonitor.py:132-135 (no after_request hook or header configuration anywhere in the app)
def create_app(db_path: Path, secure_cookies: bool = True) -> Flask:
    app = Flask(__name__)
    app.config.update(MAX_CONTENT_LENGTH=1024 * 1024, PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_DAYS),
                      SESSION_COOKIE_SECURE=secure_cookies, SESSION_COOKIE_SAMESITE="Lax")
```

```apache
# server/deploy/hallmonitor.willhackforsushi.com.conf:1-10
<VirtualHost *:80>
	...
	ProxyPreserveHost On
	ProxyPass / http://127.0.0.1:8504/
	ProxyPassReverse / http://127.0.0.1:8504/
</VirtualHost>
```

### Impact

* Any site can frame `/rooms/<id>` for a signed-in staff member (clickjacking); with no actions on
  the page, the practical effect is limited to UI redress.
* Without HSTS, a staff member who types the bare host name on a
  hostile venue network makes a first plain-HTTP request that an attacker on that network can
  intercept before the HTTPS redirect.
* Any future HTML-injection bug in `pages.py` would run script with no CSP to block it.

### Attack Scenario

1. The attacker hosts `<iframe src="https://hallmonitor.willhackforsushi.com/rooms/2">`.
2. A signed-in staff member visits the page; the `Lax` session cookie is not sent on cross-site
   subresource requests, so the frame shows the login page instead of room data. The frame still
   loads, confirming nothing forbids framing.

### Validation

Run against the local copy described in `recon.md`.

```bash
bash 04-low-missing-security-headers.sh
```

Observed output:

```
Content-Security-Policy: missing
X-Frame-Options: missing
X-Content-Type-Options: missing
Referrer-Policy: missing
Strict-Transport-Security: missing
```

Production response (`curl -v https://hallmonitor.willhackforsushi.com`, 2026-09-28 15:34 UTC),
showing the complete header set with no security headers:

```
< HTTP/1.1 302 FOUND
< Date: Mon, 28 Sep 2026 15:34:18 GMT
< Server: waitress
< Content-Length: 199
< Content-Type: text/html; charset=utf-8
< Location: /rooms
```

### References

- CWE-1021: Improper Restriction of Rendered UI Layers or Frames
- CWE-693: Protection Mechanism Failure
