# [MEDIUM] Shared staff password has no guessing limit

**Severity**: Medium
**Confidence**: High
**Category**: Missing Rate Limiting on Authentication

**Affected locations**:
- `server/hallmonitor.py:254` — `POST /login` checks the password with no attempt counting
- `server/hallmonitor.py:389` — the only password policy is a minimum of 8 characters
- `server/deploy/hallmonitor.willhackforsushi.com.conf:1` — no Apache throttling in front of the app

**Preconditions**: Unauthenticated network access to the site.

### Description

`POST /login` compares the submitted password with the single shared staff password and returns
403 on a miss. Nothing counts failures per client or overall, nothing delays responses after
failures, and nothing locks the login. The password is shared by every staff member, so it tends
to be something people can type and remember, and one correct guess opens every room. The
decision is recorded as accepted in `docs/plan.md` (open issue 9, "not for now"); this finding
documents the exposure.

Each attempt also runs Werkzeug's scrypt hash, so a high rate of parallel attempts consumes CPU on
the server that also accepts kit uploads.

### Vulnerable Code

```python
# server/hallmonitor.py:254-266
@app.post("/login")
def login():
    ...
    password_hash = get_setting(db(), "staff_password")
    ...
    if not check_password_hash(password_hash, request.form.get("password", "")):
        return pages.login_page("That password is not correct.", next_url), 403
    session.permanent = True
    session["staff"] = fingerprint(password_hash)
```

### Impact

An attacker who guesses the shared password reads the current and historical temperature,
humidity, and sensor battery for every classroom, along with every course and instructor label.
The same session stays valid for 30 days (see finding 03). Sustained parallel guessing also slows
the service for staff and kits.

### Attack Scenario

1. The attacker scripts `POST /login` with a wordlist of plausible shared passwords (course names,
   event names, seasonal patterns).
2. Every wrong guess returns 403 at the same speed; there is no lockout or growing delay.
3. The first 302 response carries a session cookie that works for `/rooms` and
   `/api/v1/rooms/<id>/readings` for 30 days.

### Validation

Run against the local copy described in `recon.md`.

```bash
bash 02-medium-login-no-rate-limit.sh
```

Observed output (local server, one client, sequential):

```
200 wrong guesses: 403 x200 in 10s
correct guess after them: 302
```

### References

- CWE-307: Improper Restriction of Excessive Authentication Attempts
