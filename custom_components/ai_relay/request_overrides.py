"""Request rules and request preview for AI Relay.

This file only exists in AI Relay, never in core, so upstream syncs do not
touch it. It hooks into every request the integration sends to the API:

- User defined rules (options of the main entry) add, override or remove body
  fields and headers right before a request is sent.
- The final request is logged at debug level.
- The ``ai_relay.preview_request`` action builds the request an entity would
  send with its current settings and returns it without sending it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextvars import ContextVar
import copy
from dataclasses import dataclass
from fnmatch import fnmatchcase
import json
import logging
from typing import Any, override

import httpx
import openai
from openai._models import FinalRequestOptions
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.selector import ObjectSelector
from homeassistant.helpers.service import async_set_service_schema

from .const import DOMAIN, LOGGER

CONF_REQUEST_RULES = "request_rules"
SERVICE_PREVIEW_REQUEST = "preview_request"

DEFAULT_PREVIEW_TEXT = "Hello"
REDACTED_HEADERS = {
    "api-key",
    "authorization",
    "cookie",
    "proxy-authorization",
    "x-api-key",
}


def _append_value(value: Any) -> dict[str, Any]:
    """Validate append: nested mappings that end in lists."""
    if not isinstance(value, dict):
        raise vol.Invalid("append expects a mapping of lists")
    for key, item in value.items():
        if isinstance(item, dict):
            _append_value(item)
        elif not isinstance(item, list):
            raise vol.Invalid(f"append: '{key}' must be a list")
    return value


RULE_SCHEMA = vol.Schema(
    {
        vol.Optional("path"): cv.string,
        vol.Optional("model"): cv.string,
        vol.Optional("remove"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("set"): vol.Schema({cv.string: object}),
        vol.Optional("append"): _append_value,
        vol.Optional("headers"): vol.Schema({cv.string: vol.Any(None, cv.string)}),
    }
)
RULES_SCHEMA = vol.All(
    vol.Any(None, RULE_SCHEMA, [RULE_SCHEMA]),
    lambda value: [] if value is None else cv.ensure_list(value),
)


class RequestPreviewed(Exception):
    """Stops a request in preview mode before it is sent.

    Deliberately neither an OpenAIError nor a HomeAssistantError, so the
    entity code and Home Assistant do not catch it.
    """


@dataclass
class _PreparedBody:
    """Body of a request before and after the rules, for display."""

    original: Any
    final: Any
    files: dict[str, str] | None
    matched_rules: list[int]


# Set by the preview action: collects the request instead of sending it.
_preview: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "ai_relay_preview", default=None
)
# Hands the body from _prepare_options to _prepare_request of the same request.
_prepared_body: ContextVar[_PreparedBody | None] = ContextVar(
    "ai_relay_prepared_body", default=None
)


class RelayAsyncOpenAI(openai.AsyncOpenAI):
    """AsyncOpenAI client that applies the request rules of a config entry."""

    def __init__(self, *args: Any, entry: ConfigEntry | None = None, **kwargs: Any):
        """Initialize the client."""
        super().__init__(*args, **kwargs)
        self.relay_entry = entry

    @override
    def copy(self, *args: Any, **kwargs: Any) -> RelayAsyncOpenAI:
        """Copy the client, keeping the config entry."""
        client = super().copy(*args, **kwargs)
        client.relay_entry = self.relay_entry
        return client

    with_options = copy

    @override
    async def _prepare_options(
        self, options: FinalRequestOptions
    ) -> FinalRequestOptions:
        """Apply the request rules to the request options."""
        options = await super()._prepare_options(options)
        _prepared_body.set(None)

        rules: list[dict[str, Any]] = []
        if self.relay_entry is not None:
            rules = self.relay_entry.options.get(CONF_REQUEST_RULES) or []

        body = options.json_data
        if options.extra_json is not None and isinstance(body, Mapping):
            body = {**body, **options.extra_json}
        elif body is None:
            body = options.extra_json
        model = body.get("model") if isinstance(body, Mapping) else None
        matched = [
            number
            for number, rule in enumerate(rules, start=1)
            if _rule_matches(rule, options.url, model)
        ]

        if not matched and not _wants_record():
            return options

        original = copy.deepcopy(body)
        if matched:
            final = copy.deepcopy(body)
            headers = dict(options.headers) if options.headers else {}
            for number in matched:
                final = _apply_rule(rules[number - 1], final, options, headers, self)
            options.json_data = final
            options.extra_json = None
            options.headers = headers
        else:
            final = original

        _prepared_body.set(
            _PreparedBody(original, final, _describe_files(options), matched)
        )
        return options

    @override
    async def _prepare_request(self, request: httpx.Request) -> None:
        """Show the final request, or stop it in preview mode."""
        await super()._prepare_request(request)
        prepared = _prepared_body.get()
        if prepared is None:
            return
        _prepared_body.set(None)

        original = _jsonable(prepared.original)
        final = _jsonable(prepared.final)
        # Short fields first: the body can be thousands of lines long.
        record: dict[str, Any] = {
            "method": request.method,
            "url": str(request.url),
            "matched_rules": prepared.matched_rules,
            "changes": _changes(original, final),
            "headers": {
                name: "**REDACTED**" if name.lower() in REDACTED_HEADERS else value
                for name, value in request.headers.items()
            },
        }
        if prepared.files:
            record["files"] = prepared.files
        record["body"] = final
        record["body_without_rules"] = original

        if (preview := _preview.get()) is not None:
            preview.append(record)
            raise RequestPreviewed

        LOGGER.debug(
            "Sending request:\n%s",
            json.dumps(
                {k: v for k, v in record.items() if k != "body_without_rules"}, indent=2
            ),
        )


def _wants_record() -> bool:
    """Return whether the current request has to be recorded."""
    return _preview.get() is not None or LOGGER.isEnabledFor(logging.DEBUG)


def _rule_matches(rule: Mapping[str, Any], path: str, model: Any) -> bool:
    """Return whether a rule applies to a request."""
    if "path" in rule and not fnmatchcase(path, rule["path"]):
        return False
    if "model" in rule and not (
        isinstance(model, str) and fnmatchcase(model, rule["model"])
    ):
        return False
    return True


def _apply_rule(
    rule: Mapping[str, Any],
    body: Any,
    options: FinalRequestOptions,
    headers: dict[str, Any],
    client: openai.AsyncOpenAI,
) -> Any:
    """Apply one rule: remove fields, set fields, append to lists, set headers."""
    if options.method.lower() != "get":
        if body is None:
            body = {}
        if isinstance(body, dict):
            for dotted in rule.get("remove", []):
                _remove(body, dotted.split("."))
            _deep_merge(body, rule.get("set", {}))
            _append(body, rule.get("append", {}))

    for name, value in rule.get("headers", {}).items():
        # Header names are case insensitive, reuse the spelling the SDK uses.
        known = [*headers, *client.default_headers, "Authorization"]
        name = next((key for key in known if key.lower() == name.lower()), name)
        headers[name] = openai.Omit() if value is None else value
    return body


def _remove(node: Any, keys: list[str]) -> None:
    """Remove a dotted path from nested dicts, if present."""
    for key in keys[:-1]:
        if not isinstance(node, dict) or key not in node:
            return
        node = node[key]
    if isinstance(node, dict):
        node.pop(keys[-1], None)


def _deep_merge(target: dict[str, Any], updates: Mapping[str, Any]) -> None:
    """Merge updates into target; nested dicts are merged, all else replaced."""
    for key, value in updates.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _append(target: dict[str, Any], updates: Mapping[str, Any]) -> None:
    """Append items to lists in target, creating missing lists."""
    for key, value in updates.items():
        if isinstance(value, Mapping):
            if not isinstance(target.get(key), dict):
                target[key] = {}
            _append(target[key], value)
        elif isinstance(target.get(key), list):
            target[key].extend(copy.deepcopy(value))
        else:
            target[key] = copy.deepcopy(value)


def _describe_files(options: FinalRequestOptions) -> dict[str, str] | None:
    """Describe the uploaded files of a multipart request."""
    if not options.files:
        return None
    files = (
        options.files.items() if isinstance(options.files, Mapping) else options.files
    )
    described = {}
    for field, file in files:
        name, content = (file[0], file[1]) if isinstance(file, tuple) else (None, file)
        size = (
            f"{len(content)} bytes"
            if isinstance(content, bytes | bytearray)
            else "stream"
        )
        described[field] = f"{name or 'file'} ({size})"
    return described


def _changes(original: Any, final: Any) -> dict[str, Any]:
    """Summarize what the rules changed in the body, by dotted path."""
    added: dict[str, Any] = {}
    changed: dict[str, Any] = {}
    removed: list[str] = []

    def walk(old: Any, new: Any, path: str) -> None:
        if (
            isinstance(old, list)
            and isinstance(new, list)
            and len(new) > len(old)
            and new[: len(old)] == old
        ):
            added[f"{path}[+]"] = new[len(old) :]
            return
        if not (isinstance(old, dict) and isinstance(new, dict)):
            if old != new:
                changed[path] = {"from": old, "to": new}
            return
        for key in old.keys() - new.keys():
            removed.append(f"{path}.{key}" if path else key)
        for key, value in new.items():
            sub = f"{path}.{key}" if path else key
            if key not in old:
                added[sub] = value
            else:
                walk(old[key], value, sub)

    walk({} if original is None else original, final, "")
    result: dict[str, Any] = {}
    if added:
        result["added"] = added
    if changed:
        result["changed"] = changed
    if removed:
        result["removed"] = sorted(removed)
    return result


def _jsonable(value: Any) -> Any:
    """Return a JSON serializable copy of a request body."""
    return json.loads(json.dumps(value, default=str))


class RequestRulesOptionsFlow(OptionsFlow):
    """Edit the request rules of an AI Relay entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and validate the request rules."""
        errors: dict[str, str] = {}
        placeholders = {"error": ""}

        if user_input is not None:
            try:
                rules = RULES_SCHEMA(user_input.get(CONF_REQUEST_RULES))
            except vol.Invalid as err:
                errors[CONF_REQUEST_RULES] = "invalid_rules"
                placeholders["error"] = str(err)
            else:
                return self.async_create_entry(
                    data={**self.config_entry.options, CONF_REQUEST_RULES: rules}
                )

        schema = vol.Schema({vol.Optional(CONF_REQUEST_RULES): ObjectSelector()})
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, user_input or self.config_entry.options
            ),
            errors=errors,
            description_placeholders=placeholders,
        )


def async_setup_preview_service(hass: HomeAssistant) -> None:
    """Register the ai_relay.preview_request action."""

    async def preview_request(call: ServiceCall) -> ServiceResponse:
        """Build the request of an entity and return it without sending it."""
        entity_id: str = call.data["entity_id"]
        text: str = call.data.get("text") or DEFAULT_PREVIEW_TEXT

        entity_entry = er.async_get(hass).async_get(entity_id)
        if entity_entry is None or entity_entry.platform != DOMAIN:
            raise ServiceValidationError(f"{entity_id} is not an AI Relay entity")

        captured: list[dict[str, Any]] = []
        token = _preview.set(captured)
        try:
            await _async_trigger_request(
                hass, call, entity_entry.domain, entity_id, text
            )
        except RequestPreviewed:
            pass
        finally:
            _preview.reset(token)

        if not captured:
            raise HomeAssistantError(f"{entity_id} did not build a request")
        return captured[0]

    hass.services.async_register(
        DOMAIN,
        SERVICE_PREVIEW_REQUEST,
        preview_request,
        schema=vol.Schema(
            {
                vol.Required("entity_id"): cv.entity_id,
                vol.Optional("text"): cv.string,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    async_set_service_schema(
        hass,
        DOMAIN,
        SERVICE_PREVIEW_REQUEST,
        {
            "name": "Preview request",
            "description": (
                "Builds the request that an AI Relay entity would send with its "
                "current settings and request rules, and returns it without "
                "sending it."
            ),
            "fields": {
                "entity_id": {
                    "name": "Entity",
                    "description": (
                        "The AI Relay conversation, AI task, text-to-speech or "
                        "speech-to-text entity."
                    ),
                    "required": True,
                    "selector": {"entity": {"integration": DOMAIN}},
                },
                "text": {
                    "name": "Text",
                    "description": (
                        "The message, task instructions or text to speak. "
                        "Speech-to-text sends one second of silence instead."
                    ),
                    "example": DEFAULT_PREVIEW_TEXT,
                    "selector": {"text": {"multiline": True}},
                },
            },
        },
    )


async def _async_trigger_request(
    hass: HomeAssistant, call: ServiceCall, domain: str, entity_id: str, text: str
) -> None:
    """Make an entity send a request the normal way."""
    # Imported here, the platforms are loaded by the time an entity exists.
    if domain == "conversation":
        from homeassistant.components import conversation  # noqa: PLC0415

        await conversation.async_converse(
            hass, text, None, call.context, agent_id=entity_id
        )
    elif domain == "ai_task":
        from homeassistant.components import ai_task  # noqa: PLC0415

        await ai_task.async_generate_data(
            hass,
            task_name="AI Relay request preview",
            entity_id=entity_id,
            instructions=text,
            context=call.context,
        )
    elif domain == "tts":
        from homeassistant.components import tts  # noqa: PLC0415

        tts_entity = hass.data[tts.DATA_COMPONENT].get_entity(entity_id)
        if tts_entity is None:
            raise HomeAssistantError(f"{entity_id} is not loaded")
        await tts_entity.async_get_tts_audio(
            text, tts_entity.default_language, dict(tts_entity.default_options or {})
        )
    elif domain == "stt":
        from homeassistant.components import stt  # noqa: PLC0415

        stt_entity = hass.data[stt.DATA_COMPONENT].get_entity(entity_id)
        if stt_entity is None:
            raise HomeAssistantError(f"{entity_id} is not loaded")
        metadata = stt.SpeechMetadata(
            language=hass.config.language,
            format=stt.AudioFormats.WAV,
            codec=stt.AudioCodecs.PCM,
            bit_rate=stt.AudioBitRates.BITRATE_16,
            sample_rate=stt.AudioSampleRates.SAMPLERATE_16000,
            channel=stt.AudioChannels.CHANNEL_MONO,
        )

        async def silence() -> AsyncIterator[bytes]:
            yield bytes(2 * 16000)

        await stt_entity.async_process_audio_stream(metadata, silence())
    else:
        raise ServiceValidationError(f"Previews are not supported for {entity_id}")
