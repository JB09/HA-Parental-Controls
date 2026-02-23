"""Config flow for Parental Controls integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .const import (
    CONF_ALLOWED_APPS,
    CONF_AUDIO_DAILY_LIMIT,
    CONF_BLOCKED_APPS,
    CONF_BLOCKED_KEYWORDS,
    CONF_CONTENT_RATING_MAX,
    CONF_FILTER_STRICTNESS,
    CONF_MAX_STRIKES,
    CONF_MONITORED_PLAYERS,
    CONF_MUSIC_RATING_MAX,
    CONF_OPENAI_AGENT_ID,
    CONF_OPENAI_ENABLED,
    CONF_MEDIA_USAGE_DAILY_LIMIT,
    CONF_MEDIA_USAGE_END,
    CONF_MEDIA_USAGE_START,
    CONF_MEDIA_USAGE_TRACK_ONLY_ALLOWED_HOURS,
    CONF_PUSH_NOTIFY_ENABLED,
    CONF_PUSH_NOTIFY_SERVICES,
    CONF_TTS_ENABLED,
    CONF_TTS_SERVICE,
    CONF_TRACKED_APPS,
    CONF_TRACKED_APPS_DAILY_LIMIT,
    CONF_USAGE_LIMIT_MODE,
    CONF_VIDEO_DAILY_LIMIT,
    CONTENT_RATINGS,
    DEFAULT_ALLOWED_APPS,
    DEFAULT_AUDIO_DAILY_LIMIT,
    DEFAULT_BLOCKED_APPS,
    DEFAULT_BLOCKED_KEYWORDS,
    DEFAULT_CONTENT_RATING,
    DEFAULT_FILTER_STRICTNESS,
    DEFAULT_MAX_STRIKES,
    DEFAULT_MEDIA_USAGE_DAILY_LIMIT,
    DEFAULT_MEDIA_USAGE_END,
    DEFAULT_MEDIA_USAGE_START,
    DEFAULT_MEDIA_USAGE_TRACK_ONLY_ALLOWED_HOURS,
    DEFAULT_MUSIC_RATING,
    DEFAULT_OPENAI_AGENT_ID,
    DEFAULT_OPENAI_ENABLED,
    DEFAULT_PUSH_NOTIFY_ENABLED,
    DEFAULT_PUSH_NOTIFY_SERVICES,
    DEFAULT_TTS_ENABLED,
    DEFAULT_TTS_SERVICE,
    DEFAULT_TRACKED_APPS,
    DEFAULT_TRACKED_APPS_DAILY_LIMIT,
    DEFAULT_USAGE_LIMIT_MODE,
    DEFAULT_VIDEO_DAILY_LIMIT,
    DOMAIN,
    FILTER_STRICTNESS_OPTIONS,
    MUSIC_RATINGS,
    USAGE_LIMIT_MODE_OPTIONS,
)


def _get_tts_service_options(
    hass: HomeAssistant,
) -> list[selector.SelectOptionDict]:
    """Build a list of available TTS options from TTS entities.

    Modern HA registers TTS engines as entities (e.g. tts.piper) rather than
    per-integration services.  We query the state machine for TTS entities,
    which mirrors the pattern used for conversation agents.
    """
    options: list[selector.SelectOptionDict] = []
    for entity_id in sorted(hass.states.async_entity_ids("tts")):
        state = hass.states.get(entity_id)
        label = (
            state.attributes.get("friendly_name", entity_id)
            if state
            else entity_id
        )
        options.append(
            selector.SelectOptionDict(value=entity_id, label=label)
        )
    return options


def _get_conversation_agent_options(
    hass: HomeAssistant,
) -> list[selector.SelectOptionDict]:
    """Build a list of available conversation agent options."""
    options: list[selector.SelectOptionDict] = []
    for entity_id in sorted(hass.states.async_entity_ids("conversation")):
        state = hass.states.get(entity_id)
        label = (
            state.attributes.get("friendly_name", entity_id)
            if state
            else entity_id
        )
        options.append(
            selector.SelectOptionDict(value=entity_id, label=label)
        )
    return options


def _build_tts_selector(
    hass: HomeAssistant,
) -> selector.SelectSelector | selector.TextSelector:
    """Build a TTS selector: dropdown with custom entry, or plain text fallback."""
    tts_options = _get_tts_service_options(hass)
    if tts_options:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=tts_options,
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
    return selector.TextSelector(
        selector.TextSelectorConfig(multiline=False)
    )


def _build_agent_selector(
    hass: HomeAssistant,
) -> selector.SelectSelector | selector.TextSelector:
    """Build a conversation agent selector: dropdown with custom entry, or plain text fallback."""
    agent_options = _get_conversation_agent_options(hass)
    if agent_options:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=agent_options,
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
    return selector.TextSelector(
        selector.TextSelectorConfig(multiline=False)
    )


def _get_mobile_app_notify_options(
    hass: HomeAssistant,
) -> list[selector.SelectOptionDict]:
    """Build a list of available mobile app notification targets.

    The HA Companion App registers notify services named ``mobile_app_<device>``.
    We enumerate services in the ``notify`` domain to find them.
    """
    options: list[selector.SelectOptionDict] = []
    notify_services = hass.services.async_services().get("notify", {})
    for service_name in sorted(notify_services):
        if service_name.startswith("mobile_app_"):
            label = service_name.replace("mobile_app_", "").replace("_", " ").title()
            options.append(
                selector.SelectOptionDict(value=service_name, label=label)
            )
    return options


def _build_mobile_app_selector(
    hass: HomeAssistant,
) -> selector.SelectSelector | selector.TextSelector:
    """Build a multi-select for mobile app notify services."""
    mobile_options = _get_mobile_app_notify_options(hass)
    if mobile_options:
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=mobile_options,
                multiple=True,
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )
    return selector.TextSelector(
        selector.TextSelectorConfig(multiline=False)
    )


class ParentalControlsConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle a config flow for Parental Controls."""

    VERSION = 3

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 1: Select media player devices to monitor."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_content_rules()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_MONITORED_PLAYERS): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="media_player",
                            multiple=True,
                        )
                    ),
                }
            ),
        )

    async def async_step_content_rules(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 2: Configure content rules."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_time_limits()

        return self.async_show_form(
            step_id="content_rules",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_BLOCKED_APPS, default=DEFAULT_BLOCKED_APPS
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=False)
                    ),
                    vol.Optional(
                        CONF_ALLOWED_APPS, default=DEFAULT_ALLOWED_APPS
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=False)
                    ),
                    vol.Optional(
                        CONF_BLOCKED_KEYWORDS, default=DEFAULT_BLOCKED_KEYWORDS
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=False)
                    ),
                    vol.Optional(
                        CONF_CONTENT_RATING_MAX, default=DEFAULT_CONTENT_RATING
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=CONTENT_RATINGS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_MUSIC_RATING_MAX, default=DEFAULT_MUSIC_RATING
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=MUSIC_RATINGS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_FILTER_STRICTNESS, default=DEFAULT_FILTER_STRICTNESS
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=FILTER_STRICTNESS_OPTIONS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_time_limits(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 3: Configure time and strike limits."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_blocking()

        return self.async_show_form(
            step_id="time_limits",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_TRACKED_APPS, default=DEFAULT_TRACKED_APPS
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=False)
                    ),
                    vol.Optional(
                        CONF_TRACKED_APPS_DAILY_LIMIT,
                        default=DEFAULT_TRACKED_APPS_DAILY_LIMIT,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=1440,
                            step=15,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_MEDIA_USAGE_DAILY_LIMIT,
                        default=DEFAULT_MEDIA_USAGE_DAILY_LIMIT,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=1440,
                            step=15,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_MEDIA_USAGE_START, default=DEFAULT_MEDIA_USAGE_START
                    ): selector.TimeSelector(),
                    vol.Optional(
                        CONF_MEDIA_USAGE_END, default=DEFAULT_MEDIA_USAGE_END
                    ): selector.TimeSelector(),
                    vol.Optional(
                        CONF_MAX_STRIKES, default=DEFAULT_MAX_STRIKES
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=10,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_MEDIA_USAGE_TRACK_ONLY_ALLOWED_HOURS,
                        default=DEFAULT_MEDIA_USAGE_TRACK_ONLY_ALLOWED_HOURS,
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_USAGE_LIMIT_MODE,
                        default=DEFAULT_USAGE_LIMIT_MODE,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=USAGE_LIMIT_MODE_OPTIONS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_VIDEO_DAILY_LIMIT,
                        default=DEFAULT_VIDEO_DAILY_LIMIT,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=1440,
                            step=15,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_AUDIO_DAILY_LIMIT,
                        default=DEFAULT_AUDIO_DAILY_LIMIT,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=1440,
                            step=15,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )

    async def async_step_blocking(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 4: Configure blocking behavior."""
        errors: dict[str, str] = {}
        if user_input is not None:
            tts_service = user_input.get(CONF_TTS_SERVICE, "")
            if tts_service and "." not in tts_service:
                errors[CONF_TTS_SERVICE] = "tts_service_invalid_format"
            else:
                self._data.update(user_input)
                return await self.async_step_openai()

        tts_selector = _build_tts_selector(self.hass)
        mobile_app_selector = _build_mobile_app_selector(self.hass)

        return self.async_show_form(
            step_id="blocking",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_TTS_ENABLED, default=DEFAULT_TTS_ENABLED
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_TTS_SERVICE, default=DEFAULT_TTS_SERVICE
                    ): tts_selector,
                    vol.Optional(
                        CONF_PUSH_NOTIFY_ENABLED, default=DEFAULT_PUSH_NOTIFY_ENABLED
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_PUSH_NOTIFY_SERVICES,
                        default=DEFAULT_PUSH_NOTIFY_SERVICES,
                    ): mobile_app_selector,
                }
            ),
            errors=errors,
        )

    async def async_step_openai(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Step 5: Configure OpenAI integration."""
        if user_input is not None:
            self._data.update(user_input)
            # Create the config entry
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title="Parental Controls",
                data=self._data,
            )

        agent_selector = _build_agent_selector(self.hass)

        return self.async_show_form(
            step_id="openai",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_OPENAI_ENABLED, default=DEFAULT_OPENAI_ENABLED
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_OPENAI_AGENT_ID, default=DEFAULT_OPENAI_AGENT_ID
                    ): agent_selector,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ParentalControlsOptionsFlow:
        """Return the options flow handler."""
        return ParentalControlsOptionsFlow()


class ParentalControlsOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Parental Controls."""

    def _get_current(self, key: str, default: Any) -> Any:
        """Get current value from options or data."""
        if key in self.config_entry.options:
            return self.config_entry.options[key]
        return self.config_entry.data.get(key, default)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage all options in a single form."""
        errors: dict[str, str] = {}
        if user_input is not None:
            tts_service = user_input.get(CONF_TTS_SERVICE, "")
            if tts_service and "." not in tts_service:
                errors[CONF_TTS_SERVICE] = "tts_service_invalid_format"
            else:
                return self.async_create_entry(title="", data=user_input)

        tts_selector = _build_tts_selector(self.hass)
        agent_selector = _build_agent_selector(self.hass)
        mobile_app_selector = _build_mobile_app_selector(self.hass)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MONITORED_PLAYERS,
                        default=self._get_current(CONF_MONITORED_PLAYERS, []),
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(
                            domain="media_player",
                            multiple=True,
                        )
                    ),
                    vol.Optional(
                        CONF_BLOCKED_APPS,
                        default=self._get_current(CONF_BLOCKED_APPS, DEFAULT_BLOCKED_APPS),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=False)
                    ),
                    vol.Optional(
                        CONF_ALLOWED_APPS,
                        default=self._get_current(CONF_ALLOWED_APPS, DEFAULT_ALLOWED_APPS),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=False)
                    ),
                    vol.Optional(
                        CONF_BLOCKED_KEYWORDS,
                        default=self._get_current(CONF_BLOCKED_KEYWORDS, DEFAULT_BLOCKED_KEYWORDS),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=False)
                    ),
                    vol.Optional(
                        CONF_CONTENT_RATING_MAX,
                        default=self._get_current(CONF_CONTENT_RATING_MAX, DEFAULT_CONTENT_RATING),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=CONTENT_RATINGS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_MUSIC_RATING_MAX,
                        default=self._get_current(CONF_MUSIC_RATING_MAX, DEFAULT_MUSIC_RATING),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=MUSIC_RATINGS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_FILTER_STRICTNESS,
                        default=self._get_current(CONF_FILTER_STRICTNESS, DEFAULT_FILTER_STRICTNESS),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=FILTER_STRICTNESS_OPTIONS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_TRACKED_APPS,
                        default=self._get_current(CONF_TRACKED_APPS, DEFAULT_TRACKED_APPS),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=False)
                    ),
                    vol.Optional(
                        CONF_TRACKED_APPS_DAILY_LIMIT,
                        default=self._get_current(CONF_TRACKED_APPS_DAILY_LIMIT, DEFAULT_TRACKED_APPS_DAILY_LIMIT),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=1440,
                            step=15,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_MEDIA_USAGE_DAILY_LIMIT,
                        default=self._get_current(CONF_MEDIA_USAGE_DAILY_LIMIT, DEFAULT_MEDIA_USAGE_DAILY_LIMIT),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=1440,
                            step=15,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_MEDIA_USAGE_START,
                        default=self._get_current(CONF_MEDIA_USAGE_START, DEFAULT_MEDIA_USAGE_START),
                    ): selector.TimeSelector(),
                    vol.Optional(
                        CONF_MEDIA_USAGE_END,
                        default=self._get_current(CONF_MEDIA_USAGE_END, DEFAULT_MEDIA_USAGE_END),
                    ): selector.TimeSelector(),
                    vol.Optional(
                        CONF_MAX_STRIKES,
                        default=self._get_current(CONF_MAX_STRIKES, DEFAULT_MAX_STRIKES),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=10,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_MEDIA_USAGE_TRACK_ONLY_ALLOWED_HOURS,
                        default=self._get_current(
                            CONF_MEDIA_USAGE_TRACK_ONLY_ALLOWED_HOURS,
                            DEFAULT_MEDIA_USAGE_TRACK_ONLY_ALLOWED_HOURS,
                        ),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_USAGE_LIMIT_MODE,
                        default=self._get_current(
                            CONF_USAGE_LIMIT_MODE, DEFAULT_USAGE_LIMIT_MODE
                        ),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=USAGE_LIMIT_MODE_OPTIONS,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        CONF_VIDEO_DAILY_LIMIT,
                        default=self._get_current(
                            CONF_VIDEO_DAILY_LIMIT, DEFAULT_VIDEO_DAILY_LIMIT
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=1440,
                            step=15,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_AUDIO_DAILY_LIMIT,
                        default=self._get_current(
                            CONF_AUDIO_DAILY_LIMIT, DEFAULT_AUDIO_DAILY_LIMIT
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0,
                            max=1440,
                            step=15,
                            unit_of_measurement="minutes",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_TTS_ENABLED,
                        default=self._get_current(CONF_TTS_ENABLED, DEFAULT_TTS_ENABLED),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_TTS_SERVICE,
                        default=self._get_current(CONF_TTS_SERVICE, DEFAULT_TTS_SERVICE),
                    ): tts_selector,
                    vol.Optional(
                        CONF_PUSH_NOTIFY_ENABLED,
                        default=self._get_current(
                            CONF_PUSH_NOTIFY_ENABLED, DEFAULT_PUSH_NOTIFY_ENABLED
                        ),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_PUSH_NOTIFY_SERVICES,
                        default=self._get_current(
                            CONF_PUSH_NOTIFY_SERVICES, DEFAULT_PUSH_NOTIFY_SERVICES
                        ),
                    ): mobile_app_selector,
                    vol.Optional(
                        CONF_OPENAI_ENABLED,
                        default=self._get_current(CONF_OPENAI_ENABLED, DEFAULT_OPENAI_ENABLED),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_OPENAI_AGENT_ID,
                        default=self._get_current(CONF_OPENAI_AGENT_ID, DEFAULT_OPENAI_AGENT_ID),
                    ): agent_selector,
                }
            ),
            errors=errors,
        )
