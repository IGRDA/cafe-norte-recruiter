-- 0002: session ownership leases, voice admission rows and private resume tokens
-- (persistence stage, PR2). Everything cascades from the session it belongs to.

-- One live lease per session. A claim by another owner succeeds only once expires_at has
-- passed; every claim increments generation, and a write fenced on an older generation fails.
create table leases (
    session_id text primary key references sessions on delete cascade,
    owner      text not null,
    generation integer not null check (generation > 0),
    expires_at timestamptz not null
);

-- One row per admitted voice session; released_at null means it still holds its place. A
-- row older than the admission ttl no longer counts, so a crashed container frees its place.
create table admission (
    id           bigint generated always as identity primary key,
    session_id   text not null references sessions on delete cascade,
    reserved_eur double precision not null check (reserved_eur >= 0),
    actual_eur   double precision check (actual_eur >= 0),
    acquired_at  timestamptz not null default now(),
    released_at  timestamptz
);
create index admission_active on admission (acquired_at) where released_at is null;

-- Only the hash of a resume token is stored; the token itself travels in the URL fragment.
create table resume_tokens (
    token_hash  text primary key,
    session_id  text not null references sessions on delete cascade,
    expires_at  timestamptz not null,
    redeemed_at timestamptz
);
create index resume_tokens_by_session on resume_tokens (session_id);
