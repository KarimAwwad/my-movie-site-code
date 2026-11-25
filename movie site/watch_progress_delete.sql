-- Gives a signed-in user full access to THEIR OWN watch_progress rows (read, save, update, delete) and nobody else's.
-- Needed for: Continue watching (read + save), and removing / finishing / clearing (delete).
-- Supabase dashboard -> SQL Editor -> paste -> Run. Safe to run more than once, and safe whether or not RLS was already on.
alter table public.watch_progress enable row level security;

drop policy if exists "Users read own progress"   on public.watch_progress;
drop policy if exists "Users insert own progress" on public.watch_progress;
drop policy if exists "Users update own progress" on public.watch_progress;
drop policy if exists "Users delete own progress" on public.watch_progress;

create policy "Users read own progress"   on public.watch_progress for select to authenticated using (auth.uid() = user_id);
create policy "Users insert own progress" on public.watch_progress for insert to authenticated with check (auth.uid() = user_id);
create policy "Users update own progress" on public.watch_progress for update to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "Users delete own progress" on public.watch_progress for delete to authenticated using (auth.uid() = user_id);

-- Check afterwards: this should list 4 rows (select, insert, update, delete).
select policyname, cmd from pg_policies where schemaname = 'public' and tablename = 'watch_progress';
