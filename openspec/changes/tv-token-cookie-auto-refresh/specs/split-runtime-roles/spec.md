## MODIFIED Requirements

### Requirement: Runtime roles are explicit
The system SHALL provide separate entrypoints for `web`, `danmaku-worker`, and `scheduler` roles.

#### Scenario: Web role starts
- **WHEN** the `web` role starts
- **THEN** it serves HTTP, SocketIO, admin APIs, internal APIs, and owns all direct business database writes without owning the danmaku WebSocket loop or scheduled background jobs

#### Scenario: Danmaku worker starts
- **WHEN** the `danmaku-worker` role starts
- **THEN** it owns the live WebSocket watcher and reports auth/status events to web/app through internal API

#### Scenario: Scheduler starts
- **WHEN** the `scheduler` role starts
- **THEN** it owns periodic triggers for guard sync, gift/stat refresh, Cookie maintenance, and expired auth cleanup, and reports job requests/results to web/app through internal API

### Requirement: Scheduler jobs execute through web-owned handlers
The system SHALL ensure scheduler-triggered jobs are executed by the web role or a web-owned runner, not merely recorded as requested tasks.

#### Scenario: Scheduler triggers Cookie maintenance
- **WHEN** the scheduler posts a `cookie-maintenance` job request to the internal API
- **THEN** the web role executes the Cookie maintenance handler, records success or failure, and leaves the job in a terminal status rather than permanently `requested`

#### Scenario: Cookie maintenance refreshes credentials
- **WHEN** the web-owned Cookie maintenance handler refreshes TV authorization successfully
- **THEN** it updates validated runtime Cookie state and increments `cookie_version` so `danmaku-worker` can reload

#### Scenario: Cookie maintenance cannot refresh credentials
- **WHEN** the web-owned Cookie maintenance handler cannot refresh authorization
- **THEN** it records a failed scheduler result with an admin-actionable error and preserves the last usable Cookie
