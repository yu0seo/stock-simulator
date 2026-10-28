-- Run once in Supabase SQL Editor BEFORE enabling Supabase keys.
begin;
create table public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
  nickname text not null unique check (char_length(nickname) between 2 and 12),
  created_at timestamptz not null default now()
);
create table public.accounts (
  user_id uuid primary key references public.profiles(user_id) on delete cascade,
  data jsonb not null,
  version bigint not null default 1
);
alter table public.profiles enable row level security;
alter table public.accounts enable row level security;
create policy own_profile on public.profiles for select to authenticated using ((select auth.uid())=user_id);
create policy own_account on public.accounts for select to authenticated using ((select auth.uid())=user_id);
-- No client writes: FastAPI checks trades, prices, learning rewards and balances.
revoke all on public.profiles, public.accounts from anon, authenticated;
grant select on public.profiles, public.accounts to authenticated;
grant all on public.profiles, public.accounts to service_role;

create function public.handle_new_user() returns trigger language plpgsql security definer set search_path='' as $$
begin
  insert into public.profiles(user_id,nickname) values(new.id,trim(new.raw_user_meta_data->>'nickname'));
  return new;
end;
$$;
create trigger on_auth_user_created after insert on auth.users for each row execute procedure public.handle_new_user();

-- Compare-and-swap protects concurrent orders/reward claims from lost updates.
create function public.save_account(p_user_id uuid,p_data jsonb,p_version bigint) returns boolean
language plpgsql security definer set search_path='' as $$
declare changed integer;
begin
  if p_version=0 then
    insert into public.accounts(user_id,data,version) values(p_user_id,p_data,1) on conflict do nothing;
  else
    update public.accounts set data=p_data,version=version+1 where user_id=p_user_id and version=p_version;
  end if;
  get diagnostics changed = row_count;
  return changed=1;
end;
$$;
revoke all on function public.save_account(uuid,jsonb,bigint) from public, anon, authenticated;
grant execute on function public.save_account(uuid,jsonb,bigint) to service_role;
revoke all on function public.handle_new_user() from public, anon, authenticated;
commit;
