# hallmonitor

Centralized classroom environment monitoring for event staff. Each instructor's classroom gets a
small kit that reads a Govee Bluetooth thermometer and hygrometer and reports to a central server.
Event staff open one page, pick a room from a drop-down, and see the current temperature,
humidity, and trend for that room.

hallmonitor grew out of thermomon, a single-classroom monitor that ran on a Mac and published a
static page over SSH. The plan for the expanded project is in [docs/plan.md](docs/plan.md).

## Layout

| Directory | Contents |
|---|---|
| `client/` | The Mac monitoring client (the original thermomon script). It becomes the first API client in Phase 1 of the plan. |
| `firmware/` | Firmware for the M5StickC Plus2 kit, with the build and flash process. |
| `server/` | The API, SQLite storage, admin tool, and staff page. |
| `docs/` | The project plan and design notes. |

## Status

Planning. The Mac client works today; the server and firmware are not built yet.
