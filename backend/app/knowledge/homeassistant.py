"""
Home Assistant control knowledge base.

This module is the single source of truth for *how* to control Home Assistant
entities from this app. It is consumed by:

  - The Smart Home → Test page UI, which uses the per-domain control hints
    to render the right widgets and call the right services.
  - The (forthcoming) Live Agent, which exposes these capabilities to the LLM
    so it can map natural-language instructions onto concrete service calls.

Authentication
--------------
All HA REST calls require:
    Authorization: Bearer <LONG_LIVED_ACCESS_TOKEN>
    Content-Type: application/json

Long-lived tokens are created in HA at: Profile (bottom-left) → Security
→ Long-Lived Access Tokens → Create Token.

Core REST endpoints we use (relative to <ha_url>/api):
    GET  /                       — health check; returns {"message": "API running."}
    GET  /config                 — HA configuration (version, location, units, components)
    GET  /states                 — list of all entity state objects
    GET  /states/{entity_id}     — single entity state
    POST /states/{entity_id}     — set state directly (rare; prefer services)
    GET  /services               — list of every registered service, grouped by domain
    POST /services/{domain}/{service}
                                 — call a service with JSON body (service_data + target)
    GET  /events                 — list of event types
    POST /events/{event_type}    — fire an event
    GET  /history/period/...     — historical state changes
    GET  /logbook/...            — human-readable log of state changes

Entity ID format
----------------
"{domain}.{object_id}", e.g. light.kitchen_ceiling, switch.fan, sensor.outside_temp.
The domain determines which services apply.

Service-call payload shape
--------------------------
POST /api/services/<domain>/<service>
{
  "entity_id": "light.kitchen" | ["light.a", "light.b"],   # target(s); optional for some services
  ... any other service-specific fields ...
}

Newer HA versions also accept a structured "target" block:
{
  "target": {"entity_id": "light.kitchen"},
  "data":   {"brightness": 128}
}
Both forms work via the REST API; we use the flat form for simplicity.

When in doubt, GET /api/services and look at the `services.<service>.fields`
dict for the real, version-correct schema. The DOMAIN_CAPABILITIES table below
is a curated convenience layer over the most common cases.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Capability schema
# ---------------------------------------------------------------------------
# Each domain entry describes:
#   description : one-line summary used in agent prompts and the UI
#   services    : {service_name: {description, params: [param_specs]}}
#
# A param spec is:
#   {name, type, description, optional?, range?, choices?, unit?}
#
# Types are JSON-friendly: "bool", "int", "float", "string", "list", "color_rgb".
# Range is [min, max] for numeric types.
# ---------------------------------------------------------------------------

DOMAIN_CAPABILITIES: dict[str, dict[str, Any]] = {
    # -- on/off devices -------------------------------------------------------
    "light": {
        "description": "Dimmable / color lights and lamps.",
        "services": {
            "turn_on": {
                "description": "Turn on (optionally set brightness, color, temperature).",
                "params": [
                    {"name": "brightness",     "type": "int",       "range": [0, 255], "optional": True, "description": "0–255 brightness"},
                    {"name": "brightness_pct", "type": "int",       "range": [0, 100], "optional": True, "description": "0–100 brightness percent"},
                    {"name": "rgb_color",      "type": "color_rgb",                    "optional": True, "description": "[R, G, B] each 0–255"},
                    {"name": "color_temp",     "type": "int",       "range": [153, 500], "optional": True, "description": "mireds (warm 500 → cool 153)"},
                    {"name": "kelvin",         "type": "int",       "range": [2000, 6500], "optional": True, "description": "color temperature in Kelvin"},
                    {"name": "transition",     "type": "float",     "optional": True, "description": "seconds to transition"},
                    {"name": "effect",         "type": "string",    "optional": True, "description": "named effect from light.effect_list"},
                ],
            },
            "turn_off": {
                "description": "Turn off.",
                "params": [
                    {"name": "transition", "type": "float", "optional": True, "description": "seconds to fade out"},
                ],
            },
            "toggle": {"description": "Toggle on/off.", "params": []},
        },
    },

    "switch": {
        "description": "Generic on/off switches and smart plugs.",
        "services": {
            "turn_on":  {"description": "Switch on.",  "params": []},
            "turn_off": {"description": "Switch off.", "params": []},
            "toggle":   {"description": "Toggle.",     "params": []},
        },
    },

    "input_boolean": {
        "description": "User-defined on/off helper (acts like a virtual switch).",
        "services": {
            "turn_on":  {"description": "Set to on.",  "params": []},
            "turn_off": {"description": "Set to off.", "params": []},
            "toggle":   {"description": "Toggle.",     "params": []},
        },
    },

    "fan": {
        "description": "Fans (with optional speed control).",
        "services": {
            "turn_on":         {"description": "Turn on (optionally at a percentage).",
                                 "params": [{"name": "percentage", "type": "int", "range": [0, 100], "optional": True}]},
            "turn_off":        {"description": "Turn off.", "params": []},
            "toggle":          {"description": "Toggle.",   "params": []},
            "set_percentage":  {"description": "Set fan speed in percent.",
                                 "params": [{"name": "percentage", "type": "int", "range": [0, 100]}]},
            "oscillate":       {"description": "Enable/disable oscillation.",
                                 "params": [{"name": "oscillating", "type": "bool"}]},
            "set_direction":   {"description": "Set rotation direction.",
                                 "params": [{"name": "direction", "type": "string", "choices": ["forward", "reverse"]}]},
            "set_preset_mode": {"description": "Set preset mode (vendor-specific).",
                                 "params": [{"name": "preset_mode", "type": "string"}]},
        },
    },

    # -- climate / hvac -------------------------------------------------------
    "climate": {
        "description": "Thermostats and HVAC units.",
        "services": {
            "set_temperature": {
                "description": "Set target temperature.",
                "params": [
                    {"name": "temperature",        "type": "float", "optional": True},
                    {"name": "target_temp_high",   "type": "float", "optional": True},
                    {"name": "target_temp_low",    "type": "float", "optional": True},
                    {"name": "hvac_mode",          "type": "string", "optional": True,
                     "choices": ["off", "heat", "cool", "heat_cool", "auto", "dry", "fan_only"]},
                ],
            },
            "set_hvac_mode": {
                "description": "Change operating mode.",
                "params": [{"name": "hvac_mode", "type": "string",
                            "choices": ["off", "heat", "cool", "heat_cool", "auto", "dry", "fan_only"]}],
            },
            "set_fan_mode":      {"description": "Set fan speed/mode.",
                                  "params": [{"name": "fan_mode", "type": "string"}]},
            "set_humidity":      {"description": "Set target humidity.",
                                  "params": [{"name": "humidity", "type": "int", "range": [0, 100]}]},
            "set_preset_mode":   {"description": "Set preset (eco, away, comfort, ...).",
                                  "params": [{"name": "preset_mode", "type": "string"}]},
            "set_swing_mode":    {"description": "Set swing mode.",
                                  "params": [{"name": "swing_mode", "type": "string"}]},
            "turn_on":           {"description": "Power on.",  "params": []},
            "turn_off":          {"description": "Power off.", "params": []},
        },
    },

    # -- covers / blinds ------------------------------------------------------
    "cover": {
        "description": "Blinds, shutters, garage doors.",
        "services": {
            "open_cover":         {"description": "Fully open.",  "params": []},
            "close_cover":        {"description": "Fully close.", "params": []},
            "stop_cover":         {"description": "Stop where it is.", "params": []},
            "toggle":             {"description": "Toggle open/closed.", "params": []},
            "set_cover_position": {"description": "Set position 0 (closed) – 100 (open).",
                                   "params": [{"name": "position", "type": "int", "range": [0, 100]}]},
            "set_cover_tilt_position": {"description": "Set tilt 0–100.",
                                        "params": [{"name": "tilt_position", "type": "int", "range": [0, 100]}]},
            "open_cover_tilt":  {"description": "Open tilt.", "params": []},
            "close_cover_tilt": {"description": "Close tilt.", "params": []},
            "stop_cover_tilt":  {"description": "Stop tilt motion.", "params": []},
        },
    },

    # -- media ---------------------------------------------------------------
    "media_player": {
        "description": "TVs, speakers, cast devices, receivers.",
        "services": {
            "turn_on":         {"description": "Power on.",  "params": []},
            "turn_off":        {"description": "Power off.", "params": []},
            "toggle":          {"description": "Toggle power.", "params": []},
            "volume_up":       {"description": "Volume up.",   "params": []},
            "volume_down":     {"description": "Volume down.", "params": []},
            "volume_mute":     {"description": "Mute/unmute.",
                                "params": [{"name": "is_volume_muted", "type": "bool"}]},
            "volume_set":      {"description": "Set absolute volume.",
                                "params": [{"name": "volume_level", "type": "float", "range": [0, 1]}]},
            "media_play":      {"description": "Play.",      "params": []},
            "media_pause":     {"description": "Pause.",     "params": []},
            "media_stop":      {"description": "Stop.",      "params": []},
            "media_play_pause":{"description": "Toggle play/pause.", "params": []},
            "media_next_track":{"description": "Skip forward.", "params": []},
            "media_previous_track": {"description": "Skip back.", "params": []},
            "media_seek":      {"description": "Seek to a position (seconds).",
                                "params": [{"name": "seek_position", "type": "float"}]},
            "select_source":   {"description": "Change input/source.",
                                "params": [{"name": "source", "type": "string"}]},
            "shuffle_set":     {"description": "Toggle shuffle.",
                                "params": [{"name": "shuffle", "type": "bool"}]},
            "play_media":      {"description": "Play arbitrary media.",
                                "params": [
                                    {"name": "media_content_id",   "type": "string"},
                                    {"name": "media_content_type", "type": "string",
                                     "description": "music | video | url | playlist | ..."}]},
        },
    },

    # -- security ------------------------------------------------------------
    "lock": {
        "description": "Smart locks.",
        "services": {
            "lock":   {"description": "Lock.",   "params": [{"name": "code", "type": "string", "optional": True}]},
            "unlock": {"description": "Unlock.", "params": [{"name": "code", "type": "string", "optional": True}]},
            "open":   {"description": "Open (latch).", "params": [{"name": "code", "type": "string", "optional": True}]},
        },
    },

    "alarm_control_panel": {
        "description": "Alarm systems.",
        "services": {
            "alarm_arm_home":     {"description": "Arm in home mode.",
                                   "params": [{"name": "code", "type": "string", "optional": True}]},
            "alarm_arm_away":     {"description": "Arm in away mode.",
                                   "params": [{"name": "code", "type": "string", "optional": True}]},
            "alarm_arm_night":    {"description": "Arm in night mode.",
                                   "params": [{"name": "code", "type": "string", "optional": True}]},
            "alarm_arm_vacation": {"description": "Arm in vacation mode.",
                                   "params": [{"name": "code", "type": "string", "optional": True}]},
            "alarm_disarm":       {"description": "Disarm.",
                                   "params": [{"name": "code", "type": "string", "optional": True}]},
            "alarm_trigger":      {"description": "Trigger alarm.", "params": []},
        },
    },

    # -- automation / scripting ---------------------------------------------
    "scene": {
        "description": "Snapshots of multiple entity states; activate to apply.",
        "services": {
            "turn_on": {"description": "Activate the scene.",
                        "params": [{"name": "transition", "type": "float", "optional": True}]},
            "apply":   {"description": "Apply an ad-hoc scene (advanced).",
                        "params": [{"name": "entities", "type": "list"}]},
        },
    },

    "script": {
        "description": "Sequences of actions defined in HA.",
        "services": {
            "turn_on":  {"description": "Run the script.", "params": []},
            "turn_off": {"description": "Stop the script.", "params": []},
            "toggle":   {"description": "Toggle.", "params": []},
        },
    },

    "automation": {
        "description": "Trigger-driven automations.",
        "services": {
            "trigger": {"description": "Run regardless of state/triggers.",
                        "params": [{"name": "skip_condition", "type": "bool", "optional": True}]},
            "turn_on":  {"description": "Enable.",  "params": []},
            "turn_off": {"description": "Disable.", "params": []},
            "toggle":   {"description": "Toggle enabled state.", "params": []},
            "reload":   {"description": "Reload all automations.", "params": []},
        },
    },

    # -- input helpers -------------------------------------------------------
    "input_number": {
        "description": "User-defined numeric helper.",
        "services": {
            "set_value": {"description": "Set the value.",
                          "params": [{"name": "value", "type": "float"}]},
            "increment": {"description": "Increment by step.", "params": []},
            "decrement": {"description": "Decrement by step.", "params": []},
        },
    },
    "input_select": {
        "description": "User-defined enum helper.",
        "services": {
            "select_option": {"description": "Pick an option.",
                              "params": [{"name": "option", "type": "string"}]},
            "select_next":   {"description": "Cycle to next option.",
                              "params": [{"name": "cycle", "type": "bool", "optional": True}]},
            "select_previous": {"description": "Cycle to previous option.",
                                "params": [{"name": "cycle", "type": "bool", "optional": True}]},
            "select_first":  {"description": "Pick first option.", "params": []},
            "select_last":   {"description": "Pick last option.",  "params": []},
        },
    },
    "input_text": {
        "description": "User-defined text helper.",
        "services": {
            "set_value": {"description": "Set the text.",
                          "params": [{"name": "value", "type": "string"}]},
        },
    },
    "input_button": {
        "description": "User-defined push-button helper.",
        "services": {"press": {"description": "Press the button.", "params": []}},
    },

    # -- vacuums -------------------------------------------------------------
    "vacuum": {
        "description": "Robot vacuums.",
        "services": {
            "start":              {"description": "Start cleaning.",      "params": []},
            "pause":              {"description": "Pause.",                "params": []},
            "stop":               {"description": "Stop cleaning.",        "params": []},
            "return_to_base":     {"description": "Send back to dock.",    "params": []},
            "locate":             {"description": "Play locate sound.",    "params": []},
            "clean_spot":         {"description": "Clean current spot.",   "params": []},
            "set_fan_speed":      {"description": "Set fan speed (named).",
                                   "params": [{"name": "fan_speed", "type": "string"}]},
            "send_command":       {"description": "Vendor-specific command.",
                                   "params": [{"name": "command", "type": "string"},
                                              {"name": "params",  "type": "dict", "optional": True}]},
        },
    },

    # -- notifications & TTS -------------------------------------------------
    "notify": {
        "description": "Send notifications (mobile push, persistent, etc.).",
        "services": {
            "*": {"description": "Service names vary per platform; check /api/services.",
                  "params": [
                      {"name": "message", "type": "string"},
                      {"name": "title",   "type": "string", "optional": True},
                      {"name": "data",    "type": "dict",   "optional": True},
                  ]},
        },
    },

    "tts": {
        "description": "Text-to-speech via media players.",
        "services": {
            "speak": {"description": "Speak text on a media player.",
                      "params": [
                          {"name": "message",          "type": "string"},
                          {"name": "media_player_entity_id", "type": "string"},
                          {"name": "language",         "type": "string", "optional": True},
                      ]},
            "clear_cache": {"description": "Clear TTS cache.", "params": []},
        },
    },

    "persistent_notification": {
        "description": "Notifications shown in HA UI.",
        "services": {
            "create":   {"description": "Create a notification.",
                         "params": [
                             {"name": "message", "type": "string"},
                             {"name": "title",   "type": "string", "optional": True},
                             {"name": "notification_id", "type": "string", "optional": True}]},
            "dismiss":  {"description": "Dismiss by id.",
                         "params": [{"name": "notification_id", "type": "string"}]},
            "dismiss_all": {"description": "Dismiss all.", "params": []},
        },
    },

    # -- read-only / state-only domains -------------------------------------
    "sensor":         {"description": "Read-only sensor values.",        "services": {}, "read_only": True},
    "binary_sensor":  {"description": "Read-only on/off sensors.",       "services": {}, "read_only": True},
    "device_tracker": {"description": "Presence / location tracking.",   "services": {}, "read_only": True},
    "person":         {"description": "Aggregate presence per person.",  "services": {}, "read_only": True},
    "weather":        {"description": "Weather entities (read-only).",   "services": {}, "read_only": True},
    "sun":            {"description": "Sun position (read-only).",       "services": {}, "read_only": True},
    "zone":           {"description": "Geographic zones (read-only).",   "services": {}, "read_only": True},
}


# Universal services that exist for almost every actor domain. We expose them
# as a fallback in the UI when a domain isn't in DOMAIN_CAPABILITIES.
UNIVERSAL_SERVICES = {
    "homeassistant": {
        "turn_on":  {"description": "Universal turn_on for supported entities.", "params": []},
        "turn_off": {"description": "Universal turn_off for supported entities.", "params": []},
        "toggle":   {"description": "Universal toggle.", "params": []},
        "update_entity": {"description": "Force an entity to refresh.", "params": []},
        "reload_config_entry": {"description": "Reload a config entry by entity_id.", "params": []},
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def capabilities_for(domain: str) -> dict[str, Any]:
    """Return the capability dict for a domain (with a universal fallback)."""
    cap = DOMAIN_CAPABILITIES.get(domain)
    if cap:
        return cap
    # Fall back: expose homeassistant.turn_on/off/toggle for unknown actor-ish
    # domains. Read-only sensors don't get a fallback.
    return {
        "description": f"Generic entity (domain `{domain}` not in knowledge base).",
        "services":    dict(UNIVERSAL_SERVICES["homeassistant"]),
        "fallback":    True,
    }


def build_service_call(domain: str, service: str, entity_id: str, **kwargs: Any) -> dict[str, Any]:
    """Build a POST /api/services/{domain}/{service} body."""
    body: dict[str, Any] = {"entity_id": entity_id}
    body.update({k: v for k, v in kwargs.items() if v is not None})
    return {
        "endpoint": f"/api/services/{domain}/{service}",
        "method":   "POST",
        "body":     body,
    }


def all_known_domains() -> list[str]:
    return sorted(DOMAIN_CAPABILITIES.keys())
