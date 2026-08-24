# Residential Collection Lease Implementation Plan

**Goal:** Ensure only one Windows runner owns a residential collection window while preserving exact-run recovery on the other PC.

**Architecture:** A private Supabase lease table serializes claims by a stable Mexico-date/window key. Every job process receives a unique holder nonce. A controlled failure releases only its own lease so recovery may continue immediately; an orphaned process retains ownership until server-calculated expiration, preventing simultaneous collection. GitHub Actions claims after dependencies and before Chrome.

## Tasks

1. Add a strict Python lease adapter and bounded CLI with acquired, busy, and invalid outcomes.
2. Add a service-role-only Supabase table and atomic claim RPC with an expiring lease and exact-owner renewal.
3. Wire primary and recovery jobs to claim the same stable window key before launching Chrome.
4. Make cloud release depend on an actually acquired collection lease for collection-backed windows.
5. Run focused tests, full Python verification, frontend verification, and code review.
