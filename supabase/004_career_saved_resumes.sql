-- Career Pro saved resume state
-- Run after the existing account/billing migrations.
-- Free users intentionally do not receive persistent resume storage.

create table if not exists public.career_saved_resumes (
  user_id uuid primary key references auth.users(id) on delete cascade,
  template_id text not null default 'minimal'
    check (template_id in (
      'minimal','classic','modern',
      'ats-standard','ats-professional','ats-executive','ats-tech'
    )),
  resume_state jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

drop trigger if exists career_saved_resumes_set_updated_at on public.career_saved_resumes;
create trigger career_saved_resumes_set_updated_at
before update on public.career_saved_resumes
for each row execute function public.set_updated_at();

alter table public.career_saved_resumes enable row level security;

-- Intentionally no browser insert/update/delete policies.
-- Persistent CV storage is a Career Pro server-side feature. The EggyPDF
-- backend validates the signed-in account + entitlement before using the
-- service-role key to read or write this table.

drop policy if exists "Users can read own saved resume" on public.career_saved_resumes;
create policy "Users can read own saved resume"
on public.career_saved_resumes for select
to authenticated
using (auth.uid() = user_id);

create index if not exists career_saved_resumes_updated_idx
on public.career_saved_resumes(updated_at desc);
