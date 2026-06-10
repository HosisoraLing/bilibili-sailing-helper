## ADDED Requirements

### Requirement: Native Bilibili live connection
The system SHALL connect to Bilibili live danmaku using an in-repo native watcher rather than `blivedm`.

#### Scenario: Watcher authenticates to live WebSocket
- **WHEN** the danmaku worker starts for a configured live room
- **THEN** it fetches danmaku server info, opens a WebSocket, sends the auth payload, and starts heartbeat

### Requirement: Protocol packets are decoded
The system SHALL decode Bilibili live packets including heartbeat replies and compressed message batches.

#### Scenario: Compressed danmaku packet is received
- **WHEN** the WebSocket receives a compressed packet containing danmaku events
- **THEN** the watcher expands it and emits normalized message events for auth matching

### Requirement: Auth events are normalized and reported
The system SHALL normalize raw Bilibili events into stable fields and report candidate auth events to the web/app internal webhook.

#### Scenario: User sends auth code
- **WHEN** a live message event contains sender UID, sender name, and text
- **THEN** the danmaku worker posts the normalized event to the internal webhook and web/app compares it with active auth sessions

### Requirement: Reconnect is observable
The system SHALL reconnect with bounded backoff and report each connection state change through internal API.

#### Scenario: WebSocket disconnects
- **WHEN** the danmaku WebSocket disconnects unexpectedly
- **THEN** the worker reports the disconnect reason, increments reconnect count, and retries without requiring web runtime restart

### Requirement: Webhook delivery is retried
The system SHALL queue candidate auth events locally in the danmaku worker and retry internal webhook delivery with bounded backoff.

#### Scenario: Web internal API is temporarily unavailable
- **WHEN** the danmaku worker detects a candidate auth event while web/app internal API is unavailable
- **THEN** the worker retries delivery and reports delivery failure in its health state without writing directly to the database
