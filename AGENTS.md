# Project instructions

Read [AGENT.md](AGENT.md) before working in this repository. It contains the user choices, implementation checkpoint, private configuration rules, verification commands and remaining work. For frontend edits, also follow `apps/web/AGENTS.md` and the installed Next.js documentation.

Never print `.env`, database URLs containing passwords, provider keys or local signing secrets. The user explicitly chose to track `.env` in this private repository; preserve that choice. Keep credential files out of shareable source archives and documentation. The default development API uses the supplied remote Supabase database; pytest must retain its isolated temporary SQLite setup. Do not run destructive test setup against Supabase.

After completing and verifying requested work, update AGENT.md so the next AI can continue, then commit and push the changes, as the user requested. Preserve tracked `.env`; private configuration edits are authorized, but never print credentials or include them in public artifacts. Use a normal fast-forward push and preserve other people's work.
