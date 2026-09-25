# Credential rotation runbook

## What happened

GitHub Push Protection blocked a push from this repository with **GH013**,
reporting two credentials inside a stray root-level `result.json` that a
"Poolside Agent" commit (`2af36d5`) had added:

| Kind | Shape | Location |
|---|---|---|
| Qwen / DashScope-style token | `AQ.<43 chars>` | `result.json:71891,71895` |
| OpenRouter API key | `sk-or-v1-<64 chars>` | `result.json:72247,72251` |

That commit was **never pushed**, so the keys were not published by that push.
It was found only because push protection refused to let the history through.

## What has already been done

1. `result.json` was purged from every commit in `main` with
   `purge_result_json.py` (an `index-filter` history rewrite touching only that
   one path).
2. The rewritten history was pushed to `origin` with `--force-with-lease`.
3. The `refs/original/` backup refs and reflog were expired and pruned, so the
   secret is not retained locally either.
4. A follow-up sweep of **all** refs and all text blobs found zero matches.

Verify any time with:

```powershell
python check_token_history.py     # probes the Telegram API for live tokens
python review_repo.py             # working-tree secret scan
```

## What still has to be done, and why only you can do it

**Purging a secret from git does not un-leak it.** The keys existed in a local
clone and in git's object store. Treat both as compromised and rotate them.
This is not optional and it is not something I can do for you — rotation
happens in someone else's account console.

### 1. OpenRouter

- <https://openrouter.ai/settings/keys>
- Revoke the key beginning `sk-or-v1-fc02567e`
- Create a replacement
- Put it somewhere git cannot see: `gx10_runner/.env` (already gitignored) or
  the host's secret store. Never in a tracked file.

### 2. Qwen / DashScope

- Alibaba Cloud console → Model Studio → API Key management
- Revoke the key beginning `AQ.Ab8RN6Ls`
- Create a replacement with only the scopes the runner actually needs

### 3. Re-point the deployment

On gx10 the runner reads secrets from `~/ufo-tg-runner-bootstrap/.env`:

```sh
scp -i ~/.ssh/id_ed25519_ufo_agent new_key.txt flak3dd@100.67.13.78:/tmp/
ssh -i ~/.ssh/id_ed25519_ufo_agent flak3dd@100.67.13.78
# edit .env, then:
docker compose -f ~/ufo-tg-runner-bootstrap/docker-compose.yml up -d --force-recreate
```

`ufo_scan.sh` reports `env VALUE <name> changed (value not shown)` when a
value changes, so you can confirm the rotation landed without the value ever
being printed or logged.

### 4. Confirm

```sh
# on gx10 - runner should still answer
docker logs --tail 20 ufo-tg-runner
cat ~/ufo-watchdog/state.json     # brain + bridge should both be true
```

## Prevention

- Push protection is on and already did its job. Leave it on.
- `review_repo.py` runs a repo-wide secret sweep. Run it before every push.
- Keep secrets in gitignored `.env` files. `ufo_bridge_token.txt` is the
  existing example.
- Note that `review_repo.py`'s patterns cover Telegram tokens, `sk-`-style keys,
  GitHub tokens, AWS keys and private keys. The OpenRouter (`sk-or-v1-`) and
  GCP (`AIza`) forms were added after push protection caught what the scanner
  missed — that gap is why GitHub's own scanner is the backstop, not a
  replacement for it.
