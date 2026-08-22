# Independent Meta Publishing Design

**Date:** 2026-08-21  
**Status:** Approved direction, awaiting written-spec review

## Goal

Publish the exact persisted public Rey Taco Picks selection to Facebook and
Instagram without sharing credentials between destinations. Instagram uses the
current Instagram Login API. Facebook keeps its Page token flow. A failure or
missing credential for one destination must not hide the result of the other.

## Fixed Decisions

- Use separate credentials for Facebook and Instagram.
- Use `graph.instagram.com/v26.0` with Instagram Login for Instagram.
- Request only `instagram_business_basic` and
  `instagram_business_content_publish` for the publishing path.
- Keep `FB_PAGE_ACCESS_TOKEN` and `FB_PAGE_ID` for the Facebook Page.
- Add `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_USER_ID` for Instagram.
- Store production tokens only in private GitHub Actions secrets. Never print,
  persist in artifacts, commit, or send them through chat.
- Treat Facebook and Instagram as independent delivery destinations.
- Publish only a persisted, public, non-parlay pick with complete source audit.

## Current Gap

`backend/social_poster.py` currently reuses `FB_PAGE_ACCESS_TOKEN` for both
destinations and calls `graph.facebook.com/v19.0` for Instagram. Its entry point
publishes only to Facebook, returns booleans, logs raw provider responses, and
does not return a failing process status when a configured delivery fails.

The current banner is a local PNG. Instagram Login content publishing requires
a publicly reachable HTTPS asset and supports JPEG for image publishing. A
local GitHub runner path cannot be passed to Instagram.

## Architecture

### Configuration

Configuration is loaded at execution time and passed into focused transports:

- Facebook: `FB_PAGE_ACCESS_TOKEN`, `FB_PAGE_ID`.
- Instagram: `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`.
- Shared non-secret API version: `META_GRAPH_VERSION`, default `v26.0`.
- Supabase upload: existing `SUPABASE_URL` and
  `SUPABASE_SERVICE_ROLE_KEY` on the trusted workflow only.

Empty credentials produce a structured `not_configured` result for that
destination. They never fall back to another platform's token.

### Public image boundary

Render one 1080-by-1080 branded JPEG from the exact persisted public pick. The
workflow uploads it with the service role to a dedicated public Supabase Storage
bucket named `social-media`. The object key is deterministic for the persisted
batch and public pick, for example `daily/<batch-id>/<pick-id>.jpg`.

Only already-public pick artwork may enter this bucket. Premium selections,
reasoning, receipts, tokens, logs, and source HTML are forbidden. The returned
public HTTPS URL is used by Instagram; Facebook receives the same local JPEG.
The first release does not automatically delete these public assets, avoiding a
race while Meta fetches the image.

### Instagram delivery

The Instagram transport uses the Instagram user token and ID only:

1. `POST https://graph.instagram.com/v26.0/<IG_ID>/media` with the public JPEG
   URL, caption, and access token.
2. Require a container ID. If processing is not immediately ready, poll the
   documented container status with a short bounded policy.
3. `POST https://graph.instagram.com/v26.0/<IG_ID>/media_publish` with the
   container ID and access token.
4. Require and record the returned media ID as the delivery receipt.

The client rejects non-HTTPS image URLs before any provider request. Captions
contain only facts from the persisted public pick, observation time, responsible
participation notice, and approved brand links/hashtags.

### Facebook delivery

The Facebook transport keeps the Page photo endpoint under the configured Graph
API version and uploads the local JPEG with its Page token. It does not depend on
Instagram configuration or outcome.

### Orchestration and idempotency

`publish_meta` returns one immutable result per configured destination:

- `success` with the remote receipt ID;
- `not_configured` when that destination is intentionally unavailable;
- `token_invalid` for a sanitized authentication/expiry classification;
- `delivery_failed` for other sanitized provider, HTTP, JSON, or timeout errors.

The command exits nonzero when any configured destination fails. It may still
report a successful sibling destination. Delivery receipts belong to the
persisted batch so a retry targets only unfinished destinations and cannot
duplicate a successful post.

Social publishing is skipped for an empty, stale, unpersisted, resumed-without-
new-data, private, or incomplete batch.

## Security and Token Lifecycle

- The token exposed in chat on 2026-08-21 is revoked and must never be reused.
- The replacement token is copied directly from Meta to GitHub Actions secrets;
  it is never read aloud, screenshotted, or written to a repository file.
- Logs include destination, status class, and exception class only. They exclude
  tokens, request bodies, response bodies, authorization URLs, and source HTML.
- Authentication failures are classified without echoing Meta's raw response.
- A `token_invalid` outcome fails the job and triggers the existing sanitized
  administrator alert path so the credential can be rotated before later posts.
- `.env.example` files contain names only and no live values.

## Workflow Changes

The social step receives separate GitHub secrets for both destinations plus the
existing Supabase service credentials needed for the public image upload. It
runs only after a new persisted public batch exists. Facebook and Instagram
outcomes are surfaced independently and the step fails when a configured
destination fails.

Until Facebook credentials are available, Instagram can operate alone with a
`not_configured` Facebook outcome. The inverse also works.

## Failure Behavior

- Missing Instagram token or ID: do not call Instagram; report
  `not_configured`.
- Missing Facebook token or ID: do not call Facebook; report `not_configured`.
- Image upload failure: make no Meta calls and fail the social delivery.
- Non-HTTPS Instagram image URL: reject locally and make no Meta calls.
- Invalid or expired token: report `token_invalid`, fail, and alert without raw
  provider data.
- Container timeout or rejected media: report `delivery_failed`; do not publish.
- One destination succeeds and the other fails: preserve the successful receipt
  and retry only the failed destination.
- No valid public pick: create no public asset and make no Meta calls.

## Testing

Implementation follows test-driven development:

- configuration tests prove tokens cannot cross destination boundaries;
- transport tests assert the Instagram host, API version, permissions-compatible
  flow, and two-step media publication;
- tests reject local, HTTP, missing, and non-JPEG Instagram assets;
- upload tests prove only the public JPEG is written to `social-media`;
- error tests prove raw provider responses and tokens never enter logs;
- orchestration tests cover independent success, failure, missing configuration,
  and retry receipts;
- workflow tests verify the new secret names and fail-closed conditions;
- source-security tests scan tracked files and built artifacts for live tokens.

No production post is used as an automated test. The final live validation is a
single controlled Instagram post derived from a reviewed public pick, followed
by receipt verification in Meta and GitHub Actions.

## Acceptance Criteria

1. Instagram publishes through `graph.instagram.com/v26.0` with
   `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_USER_ID` only.
2. Facebook publishes with its own Page token and ID only.
3. The same public JPEG and factual caption source feed both destinations.
4. Instagram receives a public HTTPS JPEG URL; no local path is sent.
5. A configured delivery failure returns a nonzero status and a sanitized
   destination-specific result.
6. A successful destination is not duplicated when its sibling is retried.
7. Missing credentials never cause a call with another platform's token.
8. No token or raw provider response appears in source, logs, artifacts, tests,
   screenshots, or chat.
9. Existing scraper, Telegram, frontend, Psalms, membership, and result behavior
   remain unchanged.

## Out of Scope

- automatic direct-message or comment management;
- paid advertising, branded content, insights, shopping, or hashtag discovery;
- non-JPEG image formats, reels, stories, carousels, or video uploads;
- guaranteeing Meta app review or future policy approval;
- automatic deletion of previously published social images;
- changing the scraper, supported markets, frontend, or Psalms feature.
