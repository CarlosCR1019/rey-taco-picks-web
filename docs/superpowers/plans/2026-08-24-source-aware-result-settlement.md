# Source-aware result settlement

1. Decode the immutable market identity persisted with every pick and grade canonical full-game markets from that identity, not from wording guesses.
2. Add conservative typed soccer statistics for team, event, half-time, and player markets; unsupported or missing evidence stays `revision_pendiente`.
3. Fetch final API-Football fixtures and only the detailed statistics needed by pending Playdoit picks, sharing a bounded daily quota and cache through Supabase.
4. Prefer one uniquely matched detailed result over the ESPN fallback, preserve compare-and-set updates, and expose the API key only to the verifier job.
5. Verify focused grading, provider, workflow, schema, full backend, and frontend build before a controlled live run.
