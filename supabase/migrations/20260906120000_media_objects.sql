begin;

create table if not exists public.media_objects (
    object_key text primary key,
    digest text not null check (digest ~ '^[0-9a-f]{64}$'),
    content_kind text not null check (
        content_kind in (
            'public_pick_story',
            'vip_teaser_story',
            'final_results_story',
            'verified_result_story',
            'ticket_evidence_story',
            'reel_cta_story',
            'daily_results_reel'
        )
    ),
    content_type text not null check (content_type in ('image/jpeg', 'video/mp4')),
    size_bytes bigint not null check (size_bytes > 0 and size_bytes <= 52428800),
    portfolio_date date not null,
    source_batch_id uuid,
    storage_backend text not null check (storage_backend in ('supabase', 'r2')),
    visibility text not null check (visibility in ('private', 'public')),
    state text not null check (state in ('approved', 'temporary', 'failed')),
    created_at timestamptz not null default now(),
    approved_at timestamptz,
    constraint media_objects_visibility_key_check check (
        visibility = 'private' or object_key like 'derived/%'
    ),
    constraint media_objects_approval_timestamp_check check (
        state <> 'approved' or approved_at is not null
    ),
    constraint media_objects_digest_identity_key_check check (
        object_key like '%/' || digest || '.jpg'
        or object_key like '%/' || digest || '.jpeg'
        or object_key like '%/' || digest || '.mp4'
    ),
    unique (digest, content_kind, portfolio_date)
);

alter table public.media_objects enable row level security;

revoke all on table public.media_objects from public, anon, authenticated;
grant select on table public.media_objects to anon, authenticated;
grant all on table public.media_objects to service_role;

drop policy if exists media_objects_public_derived on public.media_objects;
create policy media_objects_public_derived
    on public.media_objects
    for select
    using (visibility = 'public' and state = 'approved');

create index if not exists media_objects_portfolio_date_idx
    on public.media_objects (portfolio_date, content_kind);

commit;
