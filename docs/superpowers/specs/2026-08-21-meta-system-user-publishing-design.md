# Meta System User Publishing Design

**Date:** 2026-08-21  
**Status:** Approved direction, awaiting written-spec review

## Goal

Publish the exact persisted public Rey Taco Picks selection to the official
Facebook Page and Instagram professional account without an interactive login.
The process must be safe to run on GitHub Actions or either residential Windows
runner, must not duplicate a successful post on retry, and must never expose the
permanent Meta credential.

## Chosen Approach

Use the dedicated Meta Business system user `Rey Taco Automatización`. The user
has employee-level business access and only these assigned asset capabilities:

- Facebook Page: content and statistics;
- Instagram account: content and statistics;
- Meta app `Rey Taco Picks`: administer app.

The permanent system-user token is stored only as the GitHub Actions secret
`META_SYSTEM_USER_ACCESS_TOKEN`. The selected token scopes are:

- `ads_read`;
- `instagram_basic`;
- `instagram_content_publish`;
- `instagram_manage_insights`;
- `pages_manage_posts`;
- `pages_read_engagement`;
- `pages_show_list`;
- `read_insights`.

The app does not receive `ads_management`, `business_management`, messaging,
comment moderation, catalog, shopping, or branded-content scopes. `ads_read` is
read-only and is included because the Page role is assigned through Meta
Business Manager.

This replaces the rejected alternatives:

1. Instagram Login user token: least privilege but its OAuth dialog froze
   repeatedly and depends on an interactive Instagram user session.
2. Manual Meta Business Suite publishing: reliable but cannot satisfy the
   requirement to work without either owner present.

## Configuration

Production loads configuration only at runtime:

- `META_SYSTEM_USER_ACCESS_TOKEN`: the single permanent Meta credential;
- `FB_PAGE_ID`: the official Rey Taco Picks Page ID;
- `IG_USER_ID`: the connected professional Instagram account ID;
- `META_GRAPH_VERSION`: defaults to `v26.0`;
- `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`: retrieve the audited batch,
  upload the public image, and record delivery receipts;
- `GROQ_API_KEY`: optional structured copy drafting, using the key already
  configured for analysis;
- `GROQ_CONTENT_MODEL`: defaults to `openai/gpt-oss-20b`;
- `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_AI_API_TOKEN`: optional Workers AI
  background generation. Their absence never blocks publication.

The same system-user token authenticates both destinations, but destination IDs,
requests, receipts, and failure results remain independent. Empty credentials
produce a structured `not_configured` result and never fall back to another
environment variable.

## Persisted Batch Boundary

A new service-role-only Supabase RPC accepts the current stable scraper run key
(`SCRAPER_RUN_KEY` locally or `github-run:<GITHUB_RUN_ID>` in Actions) and
returns only:

- the matching persisted run ID and active batch ID;
- the run's existing delivery ledger;
- exactly one active, pending, public, non-parlay pick from that batch.

The RPC returns no premium rows or reasoning. The Python boundary revalidates
the pick's source audit and future event time before rendering or delivery. A
missing, stale, inactive, incomplete, or mismatched batch results in no upload
and no Meta request.

The existing Telegram delivery RPC remains limited to `admin`, `vip`, and
`free`. A separate service-role-only social delivery RPC accepts only
`facebook` or `instagram` and records success, the remote receipt ID, a
sanitized error class, and the update time in the same run ledger.

## Public Image Boundary

Render one deterministic 1080-by-1080 branded JPEG from the validated public
pick. The renderer receives the pick explicitly; production does not silently
load an arbitrary JSON file and does not include more than one pick. All text is
HTML-escaped and the temporary HTML/image files are created under a temporary
directory that is removed in `finally`.

The trusted workflow uploads the JPEG to a dedicated public Supabase Storage
bucket named `social-media`. The migration configures the bucket for public
JPEG reads only, with a bounded file-size limit. The deterministic object key is
`daily/<batch-id>/<pick-id>.jpg`, uploaded with upsert so a retry reuses the same
URL.

Only already-public pick artwork may enter this bucket. Premium selections,
reasoning, receipts, tokens, logs, source HTML, and sportsbook evidence pages are
forbidden. The object is retained after publication because Meta may fetch it
asynchronously.

## Optional Creative Enhancement

The branded local renderer is the required production path. It produces a
complete image from the logo palette and audited pick without any image API.
External AI is an optional decorator and can never become a publishing
dependency.

When Cloudflare Workers AI credentials are configured, the background provider
may request one text-free, logo-free, generic sports atmosphere from a
the `@cf/black-forest-labs/flux-2-dev` model. The prompt must not contain team,
league, bookmaker, or athlete trademarks. The generated bitmap is darkened and
cropped locally; the deterministic renderer then overlays every word, number,
brand element, and responsible-use notice. A timeout, rate limit, invalid image,
or unavailable model immediately selects the local branded background.

Pollinations is removed from the production path. Its former unauthenticated
endpoint no longer matches the current key-and-credit API and is unsuitable as
an unattended dependency.

Groq may draft platform-specific text for Instagram and Facebook plus reusable
article, carousel, and short-video outlines. It receives only the public content
package, never premium reasoning or tokens. Requests require JSON structured
output. A local validator then requires every factual field, rejects any number
not present in the public package, rejects omitted demo/staleness labels,
guarantees, invented probabilities, unsafe calls to action, and excess
hashtags, and enforces the responsible-use footer. Any malformed, incomplete,
or unsafe result is discarded in favor of a deterministic Spanish template.

The Psalms feature remains an independent content source. AI generation cannot
delete, rewrite, replace, or suppress the configured Psalm content.

## Meta Delivery

Both transports use `https://graph.facebook.com/v26.0` by default.

Facebook delivery:

1. POST the local JPEG to `/<FB_PAGE_ID>/photos` with the factual caption.
2. Require a returned post/photo ID.
3. Record that ID as the Facebook receipt.

Instagram delivery:

1. Reject any image URL that is not public HTTPS or does not end in the
   deterministic JPEG object.
2. POST `image_url` and the factual caption to `/<IG_USER_ID>/media`.
3. Require a container ID and poll its documented status with a short bounded
   policy when processing is not immediately complete.
4. POST the container ID to `/<IG_USER_ID>/media_publish`.
5. Require and record the returned media ID.

Captions are derived only from the persisted public row and include the event,
selection, observed price, observation time, `reytacopicks.com`, and a
responsible-participation notice. They do not promise winnings, invent
probabilities, expose premium reasoning, or claim bookmaker sponsorship.

## Orchestration and Idempotency

`publish_meta` returns one immutable result per destination:

- `success` with the remote receipt ID;
- `skipped` when that destination already has a successful ledger entry;
- `not_configured` when its required ID or token is absent;
- `token_invalid` for sanitized authentication or expiry failures;
- `delivery_failed` for other sanitized HTTP, JSON, timeout, media-status, or
  provider failures.

Before each Meta request, the orchestrator checks the persisted ledger. A
successful destination is never called again for the same run. If Facebook
succeeds and Instagram fails, a rerun calls only Instagram. Each outcome is
recorded immediately so a later process crash cannot erase the successful
receipt.

The workflow invokes social delivery after the scraper step with an `always()`
guard. The exact run-key lookup prevents an old batch from being announced if
collection failed before persistence. This also allows Meta delivery to proceed
or recover when Telegram delivery failed after the same batch was safely
persisted.

The command exits nonzero when a configured destination fails. A missing batch
is an intentional no-op because the scraper step retains responsibility for its
own failure status.

## Security and Token Lifecycle

- The permanent token never appears in source, dotenv examples, logs,
  artifacts, screenshots, chat, captions, request URLs, or provider error text.
- Requests send the token in POST form data or authorization headers, never in
  logged URLs.
- Logs contain destination, safe status class, remote receipt ID, and exception
  class only. Raw Meta response bodies are not logged.
- `.env.example` files contain variable names and empty placeholders only.
- A `token_invalid` result fails the delivery and leaves a sanitized GitHub
  Actions failure signal without printing Meta's response.
- Rotation means generating a new system-user token, replacing the single
  GitHub secret, validating one controlled request, and revoking the old token.
- The no-expiry choice removes unattended renewal outages; the limited system
  user, asset permissions, scopes, and immediate revocation procedure bound the
  impact of compromise.

## Required Repository Changes

- Replace the two-token design in `backend/social_poster.py` with an injectable,
  sanitized system-user transport and independent results.
- Add a focused Supabase-backed social batch/storage adapter rather than making
  HTTP code query arbitrary tables directly.
- Make the banner renderer accept exactly one explicit public pick and emit a
  JPEG suitable for both destinations.
- Add optional Cloudflare background and Groq copy adapters behind strict
  validators and deterministic local fallbacks; remove Pollinations from the
  production renderer.
- Add a migration for the public JPEG bucket, exact-run social batch RPC, and a
  receipt-bearing social delivery RPC limited to `facebook` and `instagram`.
- Update `.github/workflows/scraper.yml` to pass the new token and Supabase
  credentials, run social recovery safely, and remove the obsolete
  `FB_PAGE_ACCESS_TOKEN` dependency.
- Update both dotenv examples and operational documentation with names only.

## Testing

Implementation follows test-driven development:

- configuration tests prove the system-user token is required and never
  sourced from legacy destination variables;
- RPC contract tests prove only the exact run's public pick can cross the
  boundary, only the service role can execute the social RPCs, and remote
  receipt IDs are recorded without changing the Telegram RPC contract;
- renderer tests reject zero, multiple, premium, parlay, or unsafe picks and
  verify a 1080-by-1080 JPEG;
- creative-provider tests prove Cloudflare/Groq timeouts, malformed output,
  missing required facts, unsafe claims, and rate limits select local fallbacks
  without blocking delivery;
- storage tests verify the deterministic public JPEG key, MIME type, upsert, and
  rejection of non-public payloads;
- transport tests assert the Graph host/version and Facebook/Instagram request
  sequence without making live posts;
- error tests prove tokens and raw provider responses never enter logs;
- orchestration tests cover independent success, failure, missing
  configuration, durable receipts, and retry skips;
- workflow tests verify the new secret name, exact-run lookup, and `always()`
  recovery condition;
- source-security tests scan tracked files and generated artifacts for token
  patterns.

The automated suite makes no production Meta post. Final validation is one
controlled publication of a reviewed, current public pick, followed by receipt
verification in Meta, Supabase, and GitHub Actions.

## Acceptance Criteria

1. One permanent system-user secret authenticates Facebook and Instagram.
2. Both destinations use `graph.facebook.com/v26.0` by default.
3. Only the exact persisted public pick for the current run is rendered.
4. Facebook receives the local JPEG; Instagram receives the deterministic
   public HTTPS JPEG URL.
5. A successful destination is not duplicated on retry.
6. Every attempted destination records a durable, sanitized outcome.
7. A configured failure produces a nonzero exit while preserving sibling
   success.
8. No token or raw Meta response appears in source, output, artifacts,
   screenshots, or chat.
9. Existing scraper, Telegram, frontend, Psalms, membership, result checking,
   and payment behavior remain unchanged.
10. Cloudflare and Groq are optional enhancements; a failure or missing key
    still produces a valid local image and deterministic safe caption.

## Out of Scope

- direct-message or comment automation;
- creating, editing, or optimizing paid ads;
- reels, stories, carousels, video, branded content, shopping, or hashtag tools;
- automatic deletion of published social images;
- promising Meta review, verification, monetization, or future policy approval;
- AI-generated team crests, athletes, bookmaker marks, text, or numeric pick
  details;
- changes to scraper markets, frontend layout, Psalms, subscriptions, or result
  grading.
