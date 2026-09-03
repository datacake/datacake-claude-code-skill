# Datacake Agent Skill

An [Agent Skill](https://agentskills.io) that teaches Claude Code and other AI agents how to build tools, analytics, scripts and custom web or mobile frontends on the [Datacake](https://datacake.co) IoT platform using its GraphQL API (`https://api.datacake.co/graphql/`).

The skill bundles:

- `skills/datacake/SKILL.md` – the entry point: Datacake mental model, essential queries, decision guide, hard rules and workflows.
- `skills/datacake/reference/` – platform concepts, API basics, device/measurement/semantics query references, mutations, a curated schema map, the full GraphQL schema (SDL), and playbooks for Next.js and Expo apps and analytics scripts.
- `skills/datacake/scripts/` – dependency-free Python 3 helpers: `dc.py` (run GraphQL operations), `discover.py` (map a workspace: products, field identifiers, tags, semantics), `history_to_csv.py` (historical data to CSV), `fetch_schema.py` (refresh the bundled schema).

## Install

### Claude Code (personal, all projects)

```bash
git clone <this repo> ~/datacake-claude-skill
mkdir -p ~/.claude/skills
ln -s ~/datacake-claude-skill/skills/datacake ~/.claude/skills/datacake   # or copy the folder
```

Start `claude`, then ask anything about Datacake or type `/datacake`. Claude loads the skill automatically when the request mentions Datacake.

### Claude Code (project only)

Copy or symlink `skills/datacake` to `<repo>/.claude/skills/datacake` and commit it.

### Claude Code (plugin)

```bash
claude plugin install /path/to/datacake-claude-skill --scope local     # or: claude --plugin-dir /path/to/datacake-claude-skill
```

The plugin exposes the skill as `/datacake:datacake` (and `/datacake` when the name is free).

### claude.ai (web, desktop, Cowork)

Zip the `skills/datacake` folder and upload it under Settings > Capabilities > Skills. The frontmatter only uses fields from the Agent Skills specification, so the upload validates.

### Other agents (Cursor, Codex, agentskills.io-compatible tools)

Copy `skills/datacake` into the agent's skills directory (for example `.cursor/skills/datacake/` or `.codex/skills/datacake/`). Everything is plain Markdown plus Python; script paths are relative to the skill folder.

## Token setup

Create a token in Datacake (Account Settings > API Token, or a scoped API user under Members > API Users) and expose it to the scripts:

```bash
export DATACAKE_TOKEN=...            # preferred
# or
mkdir -p ~/.datacake && echo -n "..." > ~/.datacake/token && chmod 600 ~/.datacake/token
python3 skills/datacake/scripts/dc.py 'query { user { id email } }'
python3 skills/datacake/scripts/discover.py
```

Never commit tokens. The skill instructs agents to keep tokens server-side in any app they build.

## Keeping the schema current

```bash
python3 skills/datacake/scripts/fetch_schema.py --check   # what changed since the bundled schema
python3 skills/datacake/scripts/fetch_schema.py           # rewrite reference/schema.graphql and the generated blocks in reference/schema-map.md
```

## Development

```bash
python3 -m pip install --user graphql-core
python3 tools/validate_examples.py          # every ```graphql block in the skill validates against the schema
DATACAKE_TOKEN=... python3 tools/smoke_test.py   # runs the canonical queries against a real workspace (read-only)
claude plugin validate . --strict           # frontmatter and manifest checks
```

Reference files are written for agents: terse, tables, one validated example per operation. Keep `SKILL.md` under 400 lines and put detail into `reference/`.

## License

MIT. Datacake is a product of Datacake GmbH; this skill is documentation and tooling around its public API.
