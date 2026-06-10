# database-backed-auth Specification

## Purpose
Keep live danmaku authentication state durable and auditable in the web-owned database so user verification survives process restarts and worker-delivered events cannot bypass internal API authentication.

## Requirements
### Requirement: Auth state is durable
The system SHALL store auth sessions and auth attempts in the web/app-managed database as the source of truth.

#### Scenario: Danmaku success survives web restart
- **WHEN** the danmaku worker reports a matching auth event to the internal webhook and web/app marks the auth session successful
- **THEN** the web runtime can read that success after its process restarts, until the session expires or is consumed

#### Scenario: Expired session is rejected
- **WHEN** an auth session is past its expiration time
- **THEN** registration, login continuation, and reset-password continuation MUST reject it and instruct the user to restart auth

### Requirement: Auth success transition is atomic
The system SHALL allow only one valid pending auth session to transition to success for a matched UID/code pair.

#### Scenario: Duplicate matching danmaku
- **WHEN** two matching danmaku events are processed for the same session
- **THEN** exactly one success transition is recorded and later reads return one consistent successful session

### Requirement: Internal event ingestion is authenticated
The system SHALL accept worker and scheduler writes only through authenticated internal APIs.

#### Scenario: Worker reports without secret
- **WHEN** a danmaku worker webhook request omits or sends an invalid internal secret
- **THEN** the web/app backend rejects the request and does not update auth or health state

### Requirement: Worker status is persistent
The system SHALL store runtime role health in the database with timestamps, last error, last delivery error, and last event metadata.

#### Scenario: Worker reports reconnecting
- **WHEN** the danmaku worker loses its WebSocket and starts reconnecting
- **THEN** the worker reports reconnecting through internal API and the web admin status shows `danmaku-worker` as reconnecting with last error time and retry count

#### Scenario: Worker reports active Cookie version
- **WHEN** the danmaku worker sends a heartbeat after connecting or reloading Cookie
- **THEN** web/app persists the worker's active Cookie version or update timestamp with runtime health so admin status can detect stale worker Cookie state

#### Scenario: Worker stops updating heartbeat
- **WHEN** a role heartbeat is stale beyond the configured threshold
- **THEN** the admin status marks that role unhealthy and explains that the role should be restarted
