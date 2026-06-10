# native-danmaku-watcher Specification

## Purpose
Define the in-repo Bilibili live danmaku watcher contract that replaces the production `blivedm` dependency, including Cookie-aware connection setup, packet decoding, event normalization, reconnect reporting, and webhook retry behavior.

## Requirements
### Requirement: Native Bilibili live connection
The system SHALL connect to Bilibili live danmaku using an in-repo native watcher rather than `blivedm`.

#### Scenario: Watcher authenticates to live WebSocket
- **WHEN** the danmaku worker starts for a configured live room
- **THEN** it loads the current validated Cookie, fetches danmaku server info, opens a WebSocket, sends the auth payload, and starts heartbeat

### Requirement: Runtime Cookie reload is explicit
The system SHALL let the danmaku worker detect validated Cookie changes and reconnect without requiring the web process to restart the listener in-process.

#### Scenario: Worker starts with available Cookie
- **WHEN** the danmaku worker starts and web/app has a valid Cookie
- **THEN** the worker uses that Cookie for Bilibili API and WebSocket authentication and reports the Cookie version in heartbeat

#### Scenario: Worker detects newer Cookie
- **WHEN** web/app exposes a newer usable Cookie version than the worker is currently using
- **THEN** the worker closes the old WebSocket, reconnects with the new Cookie, and reports the new version and reconnect status through internal API

#### Scenario: Cookie is missing or invalid
- **WHEN** no usable Cookie is available to the worker
- **THEN** the worker reports `cookie_unavailable` or equivalent health state and admin status tells the admin to scan or repair Cookie before expecting authenticated danmaku monitoring

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
