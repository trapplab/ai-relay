# AI Relay

AI Relay is Home Assistant's built-in
[OpenAI integration](https://www.home-assistant.io/integrations/openai_conversation/)
with one addition: a configurable **API base URL**. That lets you point
conversation agents, AI tasks, speech-to-text and text-to-speech at any
OpenAI-compatible endpoint, such as LiteLLM, Ollama, vLLM, OpenRouter, an Azure
gateway or your own proxy.

Everything else behaves exactly like the core integration. The code is synced
automatically from the latest stable Home Assistant Core release.

> **Unofficial fork.** AI Relay is not affiliated with, endorsed by or
> supported by Home Assistant, Nabu Casa or OpenAI. Please report problems
> [here](https://github.com/trapplab/ai-relay/issues), not to Home Assistant.

## Installation (HACS)

1. In HACS, open **⋮ → Custom repositories**.
2. Add `https://github.com/trapplab/ai-relay` with the category **Integration**.
3. Install **AI Relay** and restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration → AI Relay**.

AI Relay uses its own domain (`ai_relay`), so it can run next to the core
OpenAI integration. Existing OpenAI entries are not migrated.

### Match your Home Assistant version

Each AI Relay release is built from one Home Assistant Core release. Its
version tells you which one: `2026.9.3` contains the integration from Core
2026.9.3, and `2026.9.3-1` is a fix on top of it. The integration pins the
same `openai` package version as that Core release. Install the AI Relay
release that matches your Home Assistant version, or dependency conflicts can
occur.

## Configuration

| Field | Description |
|-------|-------------|
| API key | The API key for your endpoint. |
| Base URL | Optional. The base URL of an OpenAI-compatible API, for example `http://litellm.local:4000/v1`. Leave it empty to use OpenAI. |

You can add the same API key more than once with different base URLs. The
re-authentication dialog also shows the base URL. Otherwise, to change it,
remove the entry and add it again.

All other options (models, prompts, web search and so on) are the same as in
the [core documentation](https://www.home-assistant.io/integrations/openai_conversation/).
Enter a model name that your endpoint serves. The defaults, such as
`gpt-4o-mini`, only work with OpenAI.

### Generate an API key

For OpenAI, create a key at
[platform.openai.com/api-keys](https://platform.openai.com/api-keys). For other
endpoints, see their documentation. Some self-hosted servers accept any value.

### Known limitations

- During setup, AI Relay calls `GET /models` to check the connection, just
  like the core integration. Endpoints that do not implement `/models` fail at
  this step.
- OpenAI-specific features (web search, code interpreter, image generation,
  service tiers) only work if your endpoint supports them.

## Maintainers

### Branches

- `upstream` contains only the output of `scripts/fetch_upstream.sh` and
  `scripts/rename_to_ai_relay.py`, with one commit per Core release. Never
  commit to it by hand.
- `main` is `upstream` plus the base URL feature and the repository
  infrastructure. Upstream changes come in with `git merge upstream` only. Do
  not rebase or squash, because that breaks the merge base.

### Upstream sync

In the repository settings, keep **Allow merge commits** enabled. Sync pull
requests must be merged with a merge commit.

To regenerate `upstream` by hand:

```sh
tag=$(scripts/fetch_upstream.sh latest-tag)
scripts/fetch_upstream.sh fetch "$tag" /tmp/core
git worktree add /tmp/upstream upstream
python3 scripts/rename_to_ai_relay.py --core /tmp/core --tag "$tag" --out /tmp/upstream
```

The repository slug and code owners used in the generated `manifest.json` are
set at the top of `scripts/rename_to_ai_relay.py`.

### Releases

Push a tag `<core-version>` (e.g. `2026.9.3`), or `<core-version>-<n>` for
fixes without an upstream change. The `version` in `manifest.json` must match
the tag. For a `-<n>` release, change it on `main` first.
`.github/workflows/release.yml` checks the version and attaches
`ai_relay.zip` to a GitHub release.

## License

Apache License 2.0, like Home Assistant Core. See [LICENSE](LICENSE) and
[NOTICE](NOTICE).
