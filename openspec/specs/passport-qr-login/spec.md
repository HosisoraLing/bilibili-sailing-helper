# passport-qr-login Specification

## Purpose
Define browserless Bilibili Passport QR login and Cookie validation behavior so admins can refresh runtime credentials without Playwright, browser automation, or replacing a known-good Cookie with an invalid one.

## Requirements
### Requirement: Browserless QR login
The system SHALL support Bilibili account QR login through HTTP Passport APIs without Playwright or a browser runtime.

#### Scenario: QR task is created
- **WHEN** an admin starts QR login
- **THEN** the system persists a QR login task with a QR URL, qrcode key, expiration time, and `pending` status

#### Scenario: QR task is polled
- **WHEN** an admin polls an active QR login task
- **THEN** the system calls the Passport poll API and updates the task status to waiting, scanned, expired, failed, or succeeded

### Requirement: Cookie integrity validation
The system SHALL validate completed Bilibili Cookies before marking them usable.

#### Scenario: Login succeeds with valid Cookie
- **WHEN** QR polling returns a successful login Cookie
- **THEN** the system validates it with Bilibili account navigation API and records account metadata, integrity status, and a monotonically changing Cookie version or update timestamp

#### Scenario: Login returns invalid Cookie
- **WHEN** Cookie validation fails
- **THEN** the system stores a failed status with an actionable admin message and MUST NOT replace the currently usable Cookie

#### Scenario: Login updates Cookie while worker is running
- **WHEN** a valid QR login replaces the usable Cookie
- **THEN** the system exposes the new Cookie version through the internal runtime contract so the danmaku worker can reload without requiring a web process restart

### Requirement: Admin-facing QR feedback
The system SHALL show QR login status in language that tells the admin what to do next.

#### Scenario: QR expires
- **WHEN** the QR login task expires before success
- **THEN** the admin status explains that the QR code expired and offers starting a new QR login

#### Scenario: Unknown Passport status
- **WHEN** Bilibili returns an unrecognized QR status code
- **THEN** the admin status records the raw code and explains that login should be retried or investigated
