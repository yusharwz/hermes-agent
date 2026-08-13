# Atlas CLI Reference

Live sources when anything looks stale: `atlas --help`, `atlas <command> --help`,
https://hermes-agent.nousresearch.com/docs/reference/cli-commands

### Global Flags

```
atlas [flags] [command]        (no subcommand = interactive chat)

  --version, -V             Show version
  -z, --oneshot PROMPT      One-shot: print ONLY the final response (for scripts/pipes)
  -m MODEL  --provider P    Model/provider override for this invocation
  -t, --toolsets LIST       Comma-separated toolsets for this invocation
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --tui / --cli             Force the Ink TUI / classic REPL
  --ignore-rules            Skip AGENTS.md/SOUL.md/memory/skill injection
  --safe-mode               Disable ALL customizations (troubleshooting)
  --pass-session-id         Include session ID in system prompt
```

### Chat

```
atlas chat [flags]
  -q, --query TEXT          Single query, non-interactive
  --image PATH              Attach a local image to a single query
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --max-turns N             Cap tool-calling iterations
  --source TAG              Session source tag (default: cli)
```
(plus the global flags above)

### Configuration

```
atlas setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
atlas model                Interactive model/provider picker
atlas fallback [add|remove|list]  Fallback provider chain
atlas config [show|edit|get|set|unset|path|env-path|check|migrate]
atlas login / logout       OAuth sign-in / clear stored auth
atlas doctor [--fix]       Check dependencies and config
atlas status [--all]       Component status
```

### Tools & Skills

```
atlas tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

atlas skills list|browse|search QUERY|inspect ID
atlas skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
atlas skills config        Enable/disable skills per platform
atlas skills check|update|uninstall|publish PATH
atlas skills tap add REPO  Add a GitHub repo as a skill source
atlas bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
atlas mcp add NAME (--url or --command) | remove | list | test NAME
atlas mcp catalog | install NAME     Curated catalog install
atlas mcp configure NAME             Toggle tool selection
atlas mcp serve                      Run Atlas as an MCP server
```
Details (transport, tool discovery, catalog): `references/native-mcp.md`.

### Gateway (Messaging Platforms)

```
atlas gateway run|install|start|stop|restart|status|setup
```

20+ platforms: Telegram, Discord, Slack, WhatsApp (Baileys + Business Cloud API), iMessage (Photon — `atlas photon setup`), Signal, Email, SMS, Matrix, Mattermost, Teams, LINE, SimpleX, ntfy, Google Chat, Home Assistant, DingTalk, Feishu, WeCom, Weixin, API Server, Webhooks. Open WebUI connects via the API Server adapter. Most adapters ship under `plugins/platforms/`.
Docs: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/

### Sessions

```
atlas sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
atlas cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
atlas webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payloads/routes: `references/webhooks.md`.

### Profiles

```
atlas profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
atlas profile rename A B | alias NAME | export NAME | import FILE
```

### Credentials & Pools

```
atlas auth                 Interactive credential manager
atlas auth add [PROVIDER]  Add OAuth or API-key credential (nous, openai-codex, qwen-oauth, …)
atlas auth list|remove P IDX|reset PROVIDER|status
```
Multiple credentials per provider form a pool that rotates automatically and skips exhausted keys.

### Other

```
atlas desktop / gui        Native desktop app
atlas dashboard            Web admin panel + embedded chat (--stop / --status)
atlas proxy                OpenAI-compatible local proxy backed by an OAuth provider
atlas portal               Quick setup / sign in via Nous Portal
atlas kanban <verb>        Multi-agent work-queue board
atlas project              Named multi-folder workspaces
atlas skin list|use|set    Switch/tweak skins (see references/themes.md)
atlas pets <verb>          Pet mascots (see references/petdex.md)
atlas memory setup|status|off|reset   Memory provider
atlas secrets bitwarden|onepassword   External secret stores
atlas moa                  Mixture-of-Agents slots
atlas hooks / security / backup / import / checkpoints / console
atlas logs [-f] [errors]   View agent/error logs
atlas send                 One-off message through a gateway platform
atlas pairing / plugins / insights / journey / computer-use
atlas acp                  ACP server (IDE integration)
atlas completion bash|zsh|fish
atlas update / uninstall / claw migrate
```

Plugin- and provider-supplied subcommands (e.g. `atlas photon setup`) only appear once their plugin is installed/active.

### Where to Find Things

| Looking for... | Location |
|---|---|
| Config options | `atlas config edit` · [Configuration docs](https://hermes-agent.nousresearch.com/docs/user-guide/configuration) |
| Tools / toolsets | `atlas tools list` · [Tools reference](https://hermes-agent.nousresearch.com/docs/reference/tools-reference) |
| Skills catalog | `atlas skills browse` · [Skills catalog](https://hermes-agent.nousresearch.com/docs/reference/skills-catalog) |
| Provider setup | `atlas model` · [Providers guide](https://hermes-agent.nousresearch.com/docs/integrations/providers) |
| Env variables | `atlas config env-path` · [Env vars reference](https://hermes-agent.nousresearch.com/docs/reference/environment-variables) |
| Gateway logs | `~/.atlas/logs/gateway.log` (or `atlas logs`) |
| Sessions | `atlas sessions browse` (reads state.db) |
