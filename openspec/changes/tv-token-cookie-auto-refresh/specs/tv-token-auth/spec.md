## ADDED Requirements

### Requirement: TV QR authorization can be created
The system SHALL allow an admin to start a Bilibili TV QR authorization flow that returns a QR URL and persists a server-side login task.

#### Scenario: Admin starts TV QR login
- **WHEN** an admin starts TV QR authorization
- **THEN** the system creates a login task with a QR URL, task identifier, expiration time, and pending status

### Requirement: TV authorization stores refreshable credentials
The system SHALL persist refreshable TV authorization metadata and extracted Web Cookies only after the returned Cookie validates successfully.

#### Scenario: TV QR login succeeds
- **WHEN** Bilibili returns a successful TV authorization payload containing `access_token`, `refresh_token`, and `cookie_info.cookies`
- **THEN** the system stores normalized credential metadata, stores the raw auth payload, validates the extracted Web Cookie, and advances the runtime Cookie version

#### Scenario: TV QR login returns invalid Web Cookie
- **WHEN** the TV authorization payload cannot produce a Web Cookie that passes validation
- **THEN** the system records a failed login state and MUST NOT replace the last usable Cookie

### Requirement: TV authorization can be refreshed
The system SHALL refresh Bilibili authorization with stored TV `access_token` and `refresh_token` before the extracted `SESSDATA` expires.

#### Scenario: Refresh succeeds
- **WHEN** Cookie maintenance refreshes a valid TV authorization
- **THEN** the system stores the new tokens, raw auth payload, Web Cookie map, expiry metadata, and increments the runtime Cookie version

#### Scenario: Refresh token is invalid
- **WHEN** Bilibili rejects the stored refresh token or returns an unrecoverable authorization error
- **THEN** the system preserves the last usable Cookie, marks the account as requiring a new scan, and reports an actionable admin status

### Requirement: TV token is not treated as a Web Cookie replacement
The system SHALL continue to expose validated Web Cookie values to existing Bilibili Web/live APIs and SHALL NOT require those APIs to use TV `access_token` directly.

#### Scenario: Runtime needs Bilibili authentication
- **WHEN** the danmaku worker or a web-owned Bilibili API call needs credentials
- **THEN** it receives a Web Cookie derived from validated `cookie_info.cookies`, not only a TV access token
