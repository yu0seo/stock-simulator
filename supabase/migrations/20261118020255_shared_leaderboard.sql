create table public.leaderboard (
  user_id text primary key check (char_length(user_id) between 1 and 100),
  nickname text not null check (char_length(nickname) between 2 and 12),
  difficulty text not null check (difficulty in ('easy','normal','hard')),
  source text not null check (source in ('sample','toss')),
  net_assets bigint not null,
  return_rate numeric not null check (return_rate not in ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)),
  completed integer not null check (completed >= 0),
  updated_at timestamptz not null
);
alter table public.leaderboard enable row level security;
revoke all on public.leaderboard from public, anon, authenticated;
grant select, insert, update on public.leaderboard to service_role;
create index leaderboard_order on public.leaderboard(source, return_rate desc);

create function public.sync_leaderboard(p_entries jsonb) returns void
language sql security invoker set search_path='' as $$
  insert into public.leaderboard(user_id,nickname,difficulty,source,net_assets,return_rate,completed,updated_at)
  select r.user_id,r.nickname,r.difficulty,r.source,r.net_assets,r.return_rate,r.completed,r.updated_at
  from pg_catalog.jsonb_to_recordset(p_entries) as r(user_id text,nickname text,difficulty text,source text,net_assets bigint,return_rate numeric,completed integer,updated_at timestamptz)
  on conflict(user_id) do update set nickname=excluded.nickname,difficulty=excluded.difficulty,
    source=excluded.source,net_assets=excluded.net_assets,return_rate=excluded.return_rate,
    completed=excluded.completed,updated_at=excluded.updated_at;
$$;
revoke all on function public.sync_leaderboard(jsonb) from public, anon, authenticated;
grant execute on function public.sync_leaderboard(jsonb) to service_role;
