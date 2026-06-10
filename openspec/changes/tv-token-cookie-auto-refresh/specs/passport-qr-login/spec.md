## MODIFIED Requirements

### Requirement: Browserless QR login
The system SHALL support browserless Bilibili account QR login without Playwright or a browser runtime, including Web Passport QR login and TV QR authorization when refreshable credentials are required.

#### Scenario: Web QR task is created
- **WHEN** an admin starts Web QR login
- **THEN** the system persists a QR login task with a QR URL, qrcode key, expiration time, and `pending` status

#### Scenario: TV QR task is created
- **WHEN** an admin starts TV QR authorization
- **THEN** the system persists a TV QR login task with the data needed to poll Bilibili and later store refreshable token metadata

#### Scenario: QR task is polled
- **WHEN** an admin polls an active QR login task
- **THEN** the system calls the matching Bilibili poll API and updates the task status to waiting, scanned, expired, failed, or succeeded

### Requirement: Cookie integrity validation
The system SHALL validate completed Bilibili Cookies before marking them usable, whether they came from Web Passport QR login or TV QR authorization refresh.

#### Scenario: Login succeeds with valid Cookie
- **WHEN** QR polling or TV authorization refresh returns a successful login Cookie
- **THEN** the system validates it with Bilibili account navigation API and records account metadata, integrity status, and a monotonically changing Cookie version or update timestamp

#### Scenario: Login returns invalid Cookie
- **WHEN** Cookie validation fails
- **THEN** the system stores a failed status with an actionable admin message and MUST NOT replace the currently usable Cookie

#### Scenario: Login updates Cookie while worker is running
- **WHEN** a valid QR login or TV authorization refresh replaces the usable Cookie
- **THEN** the system exposes the new Cookie version through the internal runtime contract so the danmaku worker can reload without requiring a web process restart
