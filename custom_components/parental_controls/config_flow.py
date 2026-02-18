"""Config flow for Parental Controls integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ALLOWED_APPS,
    CONF_BLOCKED_APPS,
    CONF_BLOCKED_KEYWORDS,
    CONF_CONTENT_RATING_MAX,
    CONF_FILTER_STRICTNESS,
    CONF_MAX_STRIKES,
    CONF_MONITORED_PLAYERS,
    CONF_MUSIC_RATING_MAX,
    CONF_OPENAI_AGENT_ID,
    CONF_OPENAI_ENABLED,
    CONF_SCREEN_TIME_DAILY_LIMIT,
    CONF_SCREEN_TIME_END,
    CONF_SCREEN_TIME_START,
    CONF_TTS_ENABLED,
    CONF_TTS_SERVICE,
    CONF_YOUTUBE_DAILY_LIMIT,
    CONTENT_RATINGS,
    DEFAULT_ALLOWED_APPS,
    DEFAULT_BLOCKED_APPS,
    DEFAULT_BLOCKED_KEYWORDS,
    DEFAULT_CONTENT_RATING,
    DEFAULT_FILTER_STRICTNESS,
    DEFAULT_MAX_STRIKES,
    DEFAULT_MUSIC_RATING,
    DEFAULT_OPENAI_AGENT_ID,
    DEFAULT_OPENAI_ENABLED,
    DEFAULT_SCREEN_TIME_DAILY_LIMIT,
    DEFAULT_SCREEN_TIME_END,
    DEFAULT_SCREEN_TIME_START,
    DEFAULT_TTS_ENABLED,
    DEFAULT_TTS_SERVICE,
    DEFAULT_YOUTUBE_DAILY_LIMIT,
    DOMAIN,
    FILTER_STRICTNESS_OPTIONS,
    MUSIC_RATINGS,
)


class ParentalControlsConfigFlow(
    config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle a config flow for Parental Controls."""

    VERSION = 1

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
                        CONF_YOUTUBE_DAILY_LIMIT,
                        default=DEFAULT_YOUTUBE_DAILY_LIMIT,
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
                        CONF_SCREEN_TIME_DAILY_LIMIT,
                        default=DEFAULT_SCREEN_TIME_DAILY_LIMIT,
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
                        CONF_SCREEN_TIME_START, default=DEFAULT_SCREEN_TIME_START
                    ): selector.TimeSelector(),
                    vol.Optional(
                        CONF_SCREEN_TIME_END, default=DEFAULT_SCREEN_TIME_END
                    ): selector.TimeSelector(),
                    vol.Optional(
                        CONF_MAX_STRIKES, default=DEFAULT_MAX_STRIKES
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=10,
                            step=1,
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

        return self.async_show_form(
            step_id="blocking",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_TTS_ENABLED, default=DEFAULT_TTS_ENABLED
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_TTS_SERVICE, default=DEFAULT_TTS_SERVICE
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=False)
                    ),
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

        return self.async_show_form(
            step_id="openai",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_OPENAI_ENABLED, default=DEFAULT_OPENAI_ENABLED
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_OPENAI_AGENT_ID, default=DEFAULT_OPENAI_AGENT_ID
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=False)
                    ),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ParentalControlsOptionsFlow:
        """Return the options flow handler."""
        return ParentalControlsOptionsFlow(config_entry)


class ParentalControlsOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Parental Controls."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

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
                        CONF_YOUTUBE_DAILY_LIMIT,
                        default=self._get_current(CONF_YOUTUBE_DAILY_LIMIT, DEFAULT_YOUTUBE_DAILY_LIMIT),
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
                        CONF_SCREEN_TIME_DAILY_LIMIT,
                        default=self._get_current(CONF_SCREEN_TIME_DAILY_LIMIT, DEFAULT_SCREEN_TIME_DAILY_LIMIT),
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
                        CONF_SCREEN_TIME_START,
                        default=self._get_current(CONF_SCREEN_TIME_START, DEFAULT_SCREEN_TIME_START),
                    ): selector.TimeSelector(),
                    vol.Optional(
                        CONF_SCREEN_TIME_END,
                        default=self._get_current(CONF_SCREEN_TIME_END, DEFAULT_SCREEN_TIME_END),
                    ): selector.TimeSelector(),
                    vol.Optional(
                        CONF_MAX_STRIKES,
                        default=self._get_current(CONF_MAX_STRIKES, DEFAULT_MAX_STRIKES),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1,
                            max=10,
                            step=1,
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
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=False)
                    ),
                    vol.Optional(
                        CONF_OPENAI_ENABLED,
                        default=self._get_current(CONF_OPENAI_ENABLED, DEFAULT_OPENAI_ENABLED),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        CONF_OPENAI_AGENT_ID,
                        default=self._get_current(CONF_OPENAI_AGENT_ID, DEFAULT_OPENAI_AGENT_ID),
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(multiline=False)
                    ),
                }
            ),
            errors=errors,
        )
