-- 0001_initial: the tables the application uses today (persistence stage, PR1).
--
-- Invariants live here, not in Python: uniqueness, foreign keys, the revision a conditional
-- update checks, one booking per slot and per session. `schema_migrations` is created by the
-- applier itself (`persistence/migrate.py`).
--
-- Later pull requests add: leases (session_id PK, owner, generation, expires_at), admission
-- (session_id PK, reserved_eur, actual_eur, acquired_at, released_at), resume_tokens
-- (token_hash PK, session_id FK, expires_at, redeemed_at), summary_jobs (session_id PK, status,
-- attempts, claimed_by, updated_at) and exports (session_id PK, schema_version, snapshot JSONB,
-- taken_at). Confirmations are derived from the journaled `state_updated` events (D25).

create table sessions (
    session_id     text primary key,
    state_json     jsonb not null,                 -- the whole SessionState, as Pydantic writes it
    access_hash    text not null,
    next_seq       integer not null default 0,     -- Postgres owns the event sequence
    created_at     timestamptz not null,           -- state.created_at, written by the store
    updated_at     timestamptz not null default now(),
    -- promoted columns are generated from the document, so they can never disagree with it
    revision       integer generated always as ((state_json -> 'candidate' ->> 'revision')::integer) stored,
    lifecycle      text generated always as (state_json ->> 'lifecycle') stored,
    outcome        text generated always as (state_json ->> 'outcome') stored,
    language       text generated always as (state_json ->> 'language') stored,
    config_id      text generated always as (state_json ->> 'config_id') stored,
    config_version text generated always as (state_json ->> 'config_version') stored,
    constraint sessions_document_names_this_session check (state_json ->> 'session_id' = session_id),
    constraint sessions_lifecycle_known
        check (lifecycle in ('active', 'paused', 'completed', 'stopped', 'abandoned', 'failed'))
);

create table turns (
    id             bigint generated always as identity primary key,  -- insertion order is `recent` order
    turn_id        text not null,
    session_id     text not null references sessions on delete cascade,
    input_id       text not null,
    role           text not null check (role in ('user', 'assistant')),
    channel        text not null check (channel in ('voice', 'text')),
    language       text not null check (language in ('es', 'en')),
    text           text not null,
    delivered_text text,
    interrupted    boolean not null default false,
    started_at     timestamptz not null,
    finished_at    timestamptz,
    constraint turns_one_record_per_input_and_role unique (session_id, input_id, role),
    constraint turns_one_record_per_turn_and_role unique (session_id, turn_id, role)
);

create table events (
    session_id text not null references sessions on delete cascade,
    seq        integer not null check (seq > 0),
    turn_id    text,
    kind       text not null,
    payload    jsonb not null,
    at         timestamptz not null,
    primary key (session_id, seq)
);

create table interview_slots (
    slot_id          text primary key,
    config_id        text not null,
    starts_at_utc    timestamptz not null,
    duration_minutes integer not null check (duration_minutes > 0)
    -- no status column: a slot is taken exactly when a bookings row names it
);
create index interview_slots_by_store on interview_slots (config_id, starts_at_utc);

create table bookings (
    -- one booking per session; no cascade on purpose: deleting a booked session must fail
    -- loudly until the retention stage decides what happens to its slot
    session_id      text primary key references sessions,
    slot_id         text not null unique references interview_slots,   -- one booking per slot
    confirmation_id text not null,
    idempotency_key text not null unique,
    committed_at    timestamptz not null default now()
);

create table usage (
    id          bigint generated always as identity primary key,
    session_id  text not null references sessions on delete cascade,
    turn_id     text,
    kind        text not null
        check (kind in ('llm_tokens', 'tts_characters', 'stt_seconds', 'media_participant_minutes')),
    quantity    double precision not null check (quantity >= 0),
    unit_detail text not null,
    estimated   boolean not null
);
create index usage_by_session on usage (session_id, id);

create table timings (
    id           bigint generated always as identity primary key,
    session_id   text not null references sessions on delete cascade,
    turn_id      text not null,
    stage        text not null,
    milliseconds integer not null check (milliseconds >= 0),
    source       text not null check (source in ('server', 'browser', 'server_proxy')),
    tool_name    text not null default ''
);
create index timings_by_session on timings (session_id, id);
