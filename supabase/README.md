# Supabase Setup

One-time setup for the classroom app's persistence layer.

## 1. Create a Supabase project

1. Go to <https://supabase.com> and sign in.
2. Click **New project**. Pick any name, any region close to you, and
   generate a database password (save it — you won't need it for this
   app but Supabase stores it).
3. Wait ~1 minute for provisioning.

## 2. Provision the schema

1. In the Supabase dashboard, open **SQL Editor → New query**.
2. Paste the contents of [`schema.sql`](./schema.sql) and run it.
3. Confirm the tables exist under **Table Editor**: `teachers`,
   `classes`, `students`, `sessions`.

Re-running the script is safe — everything is `create table if not exists`.

## 3. Copy the credentials

In the dashboard:

- **Project Settings → API** → copy the **Project URL** into
  `SUPABASE_URL`.
- Same page → under **Project API keys**, copy the **service_role**
  secret into `SUPABASE_SERVICE_ROLE_KEY`.

**Important:** the service-role key bypasses row-level security. Only
put it in trusted places (local `.env` or Streamlit Cloud secrets, not
the anon-accessible frontend of a public site). The current app is a
server-side Streamlit app, so the key never reaches the browser.

## 4. Verify

Run the app locally:

```
streamlit run app_classroom.py
```

Create a teacher account, then a class, then upload
`data/sample_roster.csv`. If that round-trip works, Supabase is wired
correctly.

## Data retention

Sessions are never auto-deleted. To wipe test data between pilot runs:

```sql
delete from public.sessions;
-- optionally:
delete from public.students;
delete from public.classes;
```

Ran from the SQL Editor. Teacher accounts survive these deletes.
