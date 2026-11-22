# Instructions for AI agents

These apply to any AI coding agent or assistant working in this repository
(Claude, Codex, Copilot, Gemini, Cursor or others).

1. **Read `CLAUDE.md`** for the working rules (versions, changelogs, tags,
   tests, the push command, writing style). They apply to every agent, not
   just Claude.
2. **Read `HANDOVER.md`** for the background: the owner's setup, what each
   add-on does, recent decisions, limitations and open ideas.
3. **Keep `HANDOVER.md` up to date.** In the same commit as any change that
   alters what someone picking this up should know (a new add-on or
   version, new or changed behaviour or settings, a decision the owner
   made or turned down, a new limitation, an idea offered but not built,
   or a change to the owner's setup), update it and bump its
   "Last updated" line. Keep it a summary, not a changelog.
4. **Never write credentials** (API keys, tokens, passwords) into code, the
   repository, logs or pages.
