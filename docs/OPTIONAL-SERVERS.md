# Optional servers: gitnexus and qmd

Model Context Protocol servers give Claude Code extra tools. Two are prepared here but
**off by default**, because each one adds to every conversation.

| Server | What it gives Claude | Install |
|--------|----------------------|---------|
| gitnexus | A code knowledge graph: who calls what, and what a change would affect. | `npm install -g gitnexus` |
| qmd | Fast local search over your Markdown notes. | `npm install -g @tobilu/qmd` |

The launchers in `mcp\` run the server and keep its error output in a log file, so a
failure at start-up can be diagnosed. `deploy\Deploy-Hooks.ps1 -Apply` copies them to
`C:\Dev\claude-hooks`.

## Turn one on

1. Uncomment its line in `manifests\npm-globals.txt` (so new computers get it) and
   install it now, in PowerShell:

   ```powershell
   npm install -g gitnexus
   ```

2. Register it for all your projects:

   ```powershell
   claude mcp add gitnexus --scope user -- C:\Dev\claude-hooks\gitnexus-mcp.cmd
   ```

   For qmd, use `qmd` and `qmd-mcp.cmd` instead.

3. For gitnexus, index each repository once, from inside that repository:

   ```powershell
   gitnexus analyze --skip-agents-md
   ```

4. Optional, gitnexus only: add the health check at session start, under `hooks` in
   `settings.json`:

   ```json
   "SessionStart": [
     { "hooks": [ { "type": "command", "command": "python -S -E C:/Dev/claude-hooks/gitnexus-health.py", "timeout": 15 } ] }
   ]
   ```

`config\mcp-servers.example.json` shows what the registration looks like. After you
register a server, `Sync-ClaudeSeat.ps1` writes your real list to `config\mcp-servers.json`
and new computers get it automatically.
