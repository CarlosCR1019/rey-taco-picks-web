begin;

alter table if exists public.tickets_ganadores
  add column if not exists telegram_chat_id bigint,
  add column if not exists file_unique_id text,
  add column if not exists received_at timestamptz not null default now();

do $$
begin
  if to_regclass('public.tickets_ganadores') is not null then
    execute 'create index if not exists tickets_ganadores_admin_received_at_idx '
      || 'on public.tickets_ganadores (telegram_chat_id, received_at)';
  end if;
end
$$;

create table if not exists public.ticket_evidence_reviews (
  evidence_key text primary key
    check (char_length(evidence_key) between 1 and 512)
    check (evidence_key ~ '^[A-Za-z0-9_-]+$'),
  batch_id uuid not null,
  portfolio_date date not null,
  state text not null check (state in ('matched','pending_review')),
  ticket_id text not null default ''
    check (ticket_id = '' or ticket_id ~ '^[0-9]{6,20}$'),
  pick_ids bigint[] not null default '{}',
  media_digest text not null check (media_digest ~ '^[0-9a-f]{64}$'),
  ocr_digest text not null check (ocr_digest ~ '^[0-9a-f]{64}$'),
  story_receipt text not null default ''
    check (story_receipt = '' or story_receipt ~ '^[A-Za-z0-9_:-]{1,256}$'),
  consumed_at timestamptz,
  reviewed_at timestamptz not null default now(),
  check (
    (state = 'matched' and ticket_id <> '' and cardinality(pick_ids) in (1, 6))
    or (state = 'pending_review' and cardinality(pick_ids) = 0)
  ),
  check (
    (story_receipt = '' and consumed_at is null)
    or (story_receipt <> '' and consumed_at is not null)
  )
);

alter table public.ticket_evidence_reviews enable row level security;

revoke all on table public.ticket_evidence_reviews
  from public, anon, authenticated;
grant select, insert, update on table public.ticket_evidence_reviews
  to service_role;

commit;
