-- 0003: the export snapshot stored at session close, and deletion that takes everything
-- with it (retention stage, D34). Deleting a session removes its simulated reservation too,
-- which is what spec §8 asks of the delete action; the slot becomes free again.

create table exports (
    session_id     text primary key references sessions on delete cascade,
    schema_version text not null,
    snapshot       jsonb not null,
    taken_at       timestamptz not null
);

alter table bookings drop constraint bookings_session_id_fkey;
alter table bookings add constraint bookings_session_id_fkey
    foreign key (session_id) references sessions on delete cascade;
