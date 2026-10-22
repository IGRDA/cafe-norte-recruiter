-- 0004: the instance that holds each voice place. A restarted instance releases the
-- places it still held, the calls a restart ended, instead of waiting for the admission ttl.
-- Rows from before this migration have no owner and age out as before.
alter table admission add column owner text not null default '';
create index admission_held_by on admission (owner) where released_at is null;
