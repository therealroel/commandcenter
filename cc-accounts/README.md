# cc-accounts

Manual CLI to juggle multiple Claude Code subscriptions and see, per account,
**when your usage limit resets** (the "is it OK to use again yet" question).

## Why

Claude Code's `~/.claude/.credentials.json` only holds ONE account's OAuth
tokens at a time. There's no built-in way to keep several subscriptions side by
side or to check how close each is to its rate limit. This tool snapshots each
account, lets you switch between them, and probes Anthropic's API to read the
real reset timestamps from the `anthropic-ratelimit-unified-*` response headers.

## Where secrets live

Tokens are stored in `~/.claude-accounts/<name>.json` with mode `0600`,
**outside this git repo**. Nothing secret is ever written into the repo.
`~/.claude-accounts/backups/` keeps timestamped copies of `.credentials.json`
from before each switch.

## Setup (one-time per account)

You log in; the tool snapshots. Repeat for each of your 3 subs:

```bash
# 1. In Claude Code, log into account A (/login), then:
./cc-acct save work

# 2. Log into account B, then:
./cc-acct save personal

# 3. Log into account C, then:
./cc-acct save third
```

Optional: put it on your PATH so you can call it from anywhere.

```bash
ln -sf "$PWD/cc-acct" ~/.local/bin/cc-acct
```

## Daily use

```bash
cc-acct status          # all accounts: usage %, rate-limit state, reset time
cc-acct status work     # just one account
cc-acct list            # saved accounts, * marks the active one
cc-acct whoami          # which account is active right now
cc-acct switch personal # make 'personal' active (restart Claude Code after)
cc-acct refresh work    # force an OAuth token refresh
cc-acct rm third        # forget a saved account
```

### Example `status` output

```
work  [you@company.com] (active)
  5-hour window: rejected  usage  101%  resets 2026-06-04 06:00:00 CEST (in 2h 14m)
  weekly window: allowed   usage   10%  resets 2026-06-10 ...
  >> RATE LIMITED (out_of_credits)
  >> OK again at 2026-06-04 06:00:00 CEST  (in 2h 14m)

personal  [you@gmail.com]
  5-hour window: allowed   usage    3%  ...
  >> OK to use now
```

## How it works

- `save` reads tokens from `~/.claude/.credentials.json` and the account
  identity block from `~/.claude.json`, writes both to the private store.
- `status` makes a tiny 1-token request per account and parses the rate-limit
  headers Anthropic returns. Access tokens expire ~daily, so it auto-refreshes
  using the stored refresh token and writes the rotated token back.
- `switch` backs up the current credentials, then swaps in the chosen account's
  tokens + identity. Restart Claude Code afterwards to pick up the change.

## Notes / caveats

- Refresh tokens rotate on use: only one copy is valid at a time. Always let the
  tool persist refreshes (it does this automatically) rather than refreshing the
  same account from two places.
- If a refresh fails (`invalid_grant`), that account's stored refresh token was
  superseded — just `/login` again in Claude Code and re-run `cc-acct save <name>`.
- Requires only Python 3 standard library. No dependencies.
