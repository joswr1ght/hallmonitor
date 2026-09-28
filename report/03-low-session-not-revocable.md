# [LOW] Staff sessions survive logout and last 30 days

**Severity**: Low
**Confidence**: High
**Category**: Session Management

**Affected locations**:
- `server/hallmonitor.py:134` — `PERMANENT_SESSION_LIFETIME` of 30 days on a client-side signed cookie
- `server/hallmonitor.py:207` — `is_staff` accepts any cookie carrying the current password fingerprint
- `server/hallmonitor.py:269` — `/logout` clears only the browser's copy

**Preconditions**: The attacker holds a copy of a staff session cookie (a shared or borrowed
laptop, browser sync, a proxy log, or malware on a staff device).

### Description

Staff sessions are Flask signed cookies that hold the fingerprint of the current password hash.
The server keeps no session records, so `/logout` only tells the browser to drop its cookie. Any
copy of the cookie keeps working until 30 days after it was issued. The only server-side way to
end a session is to change the shared password, which signs out every staff member at once.

### Vulnerable Code

```python
# server/hallmonitor.py:134-135
app.config.update(MAX_CONTENT_LENGTH=1024 * 1024, PERMANENT_SESSION_LIFETIME=timedelta(days=SESSION_DAYS),
                  SESSION_COOKIE_SECURE=secure_cookies, SESSION_COOKIE_SAMESITE="Lax")
```

```python
# server/hallmonitor.py:207-209
def is_staff() -> bool:
    password_hash = get_setting(db(), "staff_password")
    return password_hash is not None and session.get("staff") == fingerprint(password_hash)
```

```python
# server/hallmonitor.py:269-272
@app.get("/logout")
def logout():
    session.clear()
    return redirect("/login")
```

### Impact

A captured cookie reads every room's readings for up to 30 days, even after the staff member
signs out. Removing one person's access requires rotating the shared password and redistributing
it to all staff.

### Attack Scenario

1. A staff member signs in on a shared machine at a venue and later clicks "Sign out".
2. An attacker who copied the `session` cookie before the sign-out replays it.
3. `GET /api/v1/rooms` and the readings endpoints return 200 until the cookie's 30-day expiry or a
   password change.

### Validation

Run against the local copy described in `recon.md`.

```bash
bash 03-low-session-not-revocable.sh
```

Observed output:

```
before logout: 200
after logout, same cookie: 200
```

### References

- CWE-613: Insufficient Session Expiration
