## ADDED Requirements

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

### Requirement: Internal API boundary is explicit
The system SHALL use `INTERNAL_API_URL` and `INTERNAL_API_SECRET` for role-to-web communication.

#### Scenario: Worker posts an internal event
- **WHEN** `danmaku-worker` or `scheduler` sends an internal request
- **THEN** the request targets `web` internal API, includes the configured secret, and does not require direct database file access from that role

### Requirement: Docker configuration is consistent
The system SHALL use one canonical internal web port across sample settings, Dockerfile exposure, Compose service port, and healthcheck URL.

#### Scenario: Compose config is rendered
- **WHEN** Docker Compose configuration is validated
- **THEN** the web service port mapping and healthcheck target point to the same internal Flask port

### Requirement: Runtime update is deployment-owned
The system SHALL NOT run `git pull` or mutate application code from normal business runtime startup.

#### Scenario: App starts in production
- **WHEN** any runtime role starts
- **THEN** it does not update source code and logs only the current version/config state

### Requirement: Admin health is role-based
The system SHALL expose role-level health for web, danmaku worker, and scheduler.

#### Scenario: Scheduler fails but web is healthy
- **WHEN** the scheduler records a failed job while web continues serving
- **THEN** admin status shows scheduler failure separately and does not imply the web server is down
