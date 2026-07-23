# supabase

**PLACEHOLDER — owned by WS0.3.**

Supabase (Postgres + Auth) is the platform's **managed, off-box** state store and
auth provider. It is **not** a Docker Compose service — only its connection env is
wired here (see `.env.example`: `SUPABASE_URL`, `SUPABASE_ANON_KEY`,
`SUPABASE_SERVICE_ROLE_KEY`).

Schema, migrations, and auth policy land in WS0.3. Nothing here should be
implemented until then.
