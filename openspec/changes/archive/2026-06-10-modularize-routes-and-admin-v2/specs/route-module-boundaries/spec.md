# route-module-boundaries Specification

## Purpose

Define how route handlers are split into focused modules without changing user-visible URLs, endpoint names, admin protections, or internal API contracts.

## ADDED Requirements

### Requirement: Route registration remains compatible

The system SHALL preserve existing URL rules, HTTP methods, endpoint names, and Blueprint prefixes while route handlers are moved out of the monolithic route module.

#### Scenario: Templates generate existing URLs

- **WHEN** templates call `url_for()` for existing public, auth, or admin endpoints
- **THEN** URL generation succeeds without changing template endpoint names unless an explicit compatibility shim is provided

#### Scenario: Route inventory is compared after modularization

- **WHEN** the app registers routes after modularization
- **THEN** the route inventory matches the pre-modularization inventory for URL rules, endpoint names, methods, and Blueprint prefixes

### Requirement: Route modules do not absorb business logic

Route modules SHALL delegate business decisions and data mutations to service modules instead of moving service logic into route handlers.

#### Scenario: Admin guard route is moved

- **WHEN** an admin guard route is moved into a focused module
- **THEN** guard fetching, mutation, cache invalidation, and CSV generation remain in existing services or dedicated helpers rather than being duplicated in the route module

### Requirement: Admin protection is preserved

Admin route modules SHALL preserve the same admin checks and failure behavior as the monolithic route module.

#### Scenario: Non-admin accesses an admin route

- **WHEN** a non-admin request reaches an admin route after modularization
- **THEN** the response behavior remains compatible with the pre-modularization behavior

### Requirement: Internal API contracts remain stable

Internal route modules SHALL preserve request authentication, response status codes, and JSON response shapes for runtime worker and scheduler endpoints.

#### Scenario: Worker omits internal secret

- **WHEN** `danmaku-worker` or `scheduler` calls an internal endpoint without a valid secret
- **THEN** the endpoint still returns the same unauthorized response and performs no state mutation

### Requirement: Public auth flow remains user-actionable

Public auth routes SHALL preserve the current action-oriented states for waiting, success, expired, listener unavailable, delivery delayed, and retrying.

#### Scenario: Auth status is pending

- **WHEN** a user polls auth status before a matching danmaku event is processed
- **THEN** the response still tells the user the next action rather than returning only a technical state
