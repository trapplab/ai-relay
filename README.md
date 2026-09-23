# <img src="custom_components/ai_relay/brand/icon.png" alt="" width="48" align="absmiddle"> AI Relay

> ## TLDR;
> 
> AI Relay is Home Assistant's built-in
[OpenAI integration](https://www.home-assistant.io/integrations/openai_conversation/)
with one addition: a configurable **API base URL**. (and some additional configurations exposed)

This integration lets you point
conversation agents, AI tasks, speech-to-text and text-to-speech at any
OpenAI-compatible endpoint, such as LiteLLM, Ollama, vLLM, OpenRouter, an Azure
gateway or your own proxy.

Everything else behaves exactly like the core integration. The code is synced
automatically from the latest stable Home Assistant Core release. This keeps the effort low to have this repository maintained.

> **Unofficial fork.** AI Relay is not affiliated with, endorsed by or
> supported by Home Assistant, Nabu Casa or OpenAI. Please report problems
> [here](https://github.com/trapplab/ai-relay/issues), not to Home Assistant.
> 
## What to expect
- Regular updates synced automatically from Home Assistant Core.
- New features if they appear in the stable OpenAI Integration of Home Assistant.
- Some more configurations are exposed then on the original integration

## What to not expect
- Custom features (except small configuration changes)

## Installation (HACS)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=trapplab&repository=ai-relay&category=integration)

Click the button above to open AI Relay in HACS on your Home Assistant
instance, or add it by hand:

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

## Tested providers

| Provider | Conversation | Speech-to-text | Text-to-speech |
|----------|:---:|:---:|:---:|
| OpenAI | — | — | — |
| Kilo Gateway | ✅ | ❌ | ❌ |
| Mistral | — | ✅ | ⚠️ |

* ✅ works
* ⚠️ endpoint is not fully OpenAI-compatible: It needs a proxy such as [LiteLLM](https://docs.litellm.ai/) that translates the requests
* ❌ does not work
* — not tested

Tested another provider? Please report the
result in an [issue](https://github.com/trapplab/ai-relay/issues).


## License

Apache License 2.0, like Home Assistant Core. See [LICENSE](LICENSE) and
[NOTICE](NOTICE).
