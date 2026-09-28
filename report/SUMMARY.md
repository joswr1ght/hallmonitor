# Findings Summary

Target: hallmonitor server (`server/`) and kit setup portal (`firmware/src/portal.cpp`). Findings
were validated against a local copy of the current server code (see [recon.md](recon.md)); the only
production request was a plain `GET /`, which confirmed finding 04.

| # | Severity | Confidence | Category | Title | Finding |
|---|----------|------------|----------|-------|---------|
| 01 | Medium | High | Open Redirect | Open redirect after staff login through a tab in `next` | [01-medium-open-redirect-login.md](01-medium-open-redirect-login.md) |
| 02 | Medium | High | Missing Rate Limiting | Shared staff password has no guessing limit | [02-medium-login-no-rate-limit.md](02-medium-login-no-rate-limit.md) |
| 03 | Low | High | Session Management | Staff sessions survive logout and last 30 days | [03-low-session-not-revocable.md](03-low-session-not-revocable.md) |
| 04 | Low | High | Missing Security Headers | No browser security headers on the staff pages | [04-low-missing-security-headers.md](04-low-missing-security-headers.md) |
