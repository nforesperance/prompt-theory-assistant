-- =====================================================================
-- Supabase schema for the Teaching Assistant classroom deployment.
--
-- Run once in the Supabase SQL Editor (Project → SQL → New query).
-- Idempotent: safe to re-run.
-- =====================================================================

create table if not exists public.teachers (
  email         text primary key,
  name          text not null,
  password_hash text not null,
  created_at    timestamptz not null default now()
);

create table if not exists public.classes (
  id                bigserial primary key,
  teacher_email     text not null references public.teachers(email) on delete cascade,
  name              text not null,
  session_code      text not null unique,
  topic             text,
  theory            text not null,
  provider          text not null default 'openai',
  model             text,
  adaptive_routing  boolean not null default true,
  created_at        timestamptz not null default now()
);

create table if not exists public.students (
  class_id        bigint not null references public.classes(id) on delete cascade,
  student_id      text not null,
  display_name    text not null,
  grade_level     int,
  reading_level   text,
  language        text default 'en',
  accommodations  text,
  notes           text,
  primary key (class_id, student_id)
);

create table if not exists public.sessions (
  id              bigserial primary key,
  class_id        bigint not null references public.classes(id) on delete cascade,
  student_id      text not null,
  started_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  state           jsonb not null,
  transcript      jsonb not null default '[]'::jsonb
);

create index if not exists idx_sessions_class_student
    on public.sessions(class_id, student_id, updated_at desc);

-- =====================================================================
-- Row-Level Security
--
-- The Streamlit backend uses the SERVICE_ROLE key, which bypasses RLS.
-- RLS is therefore defence-in-depth: if anyone ever obtains the ANON
-- key and hits the REST API directly, they get nothing. All real
-- authorisation is enforced in the Python layer.
-- =====================================================================

alter table public.teachers enable row level security;
alter table public.classes  enable row level security;
alter table public.students enable row level security;
alter table public.sessions enable row level security;

-- No policies defined => anon role is denied by default. The service
-- role (used by the backend) bypasses RLS entirely.
