# Home Assistant integration notes

This document is the human-readable companion to
[`backend/app/knowledge/homeassistant.py`](../backend/app/knowledge/homeassistant.py),
which is the *machine-readable* source of truth used by the Test UI and the
forthcoming Live Agent.

## Authentication

Every REST call needs:

```
Authorization: Bearer <LONG_LIVED_ACCESS_TOKEN>
Content-Type: application/json
```

Get a long-lived token in HA: **Profile → Security → Long-Lived Access Tokens
→ Create Token**.

## Key REST endpoints

Base URL is `<ha_url>/api`.

| Verb | Path | Notes |
| ---- | ---- | ----- |
| GET  | `/` | Health probe. Returns `{"message": "API running."}` when authorized. 401 = bad token. |
| GET  | `/config` | HA version, location, units, loaded components. |
| GET  | `/states` | All entities with current state and attributes. |
| GET  | `/states/{entity_id}` | Single entity. |
| POST | `/states/{entity_id}` | Set state directly. Rarely needed — prefer services. |
| GET  | `/services` | Every registered service, grouped by domain, with field schemas. |
| POST | `/services/{domain}/{service}` | Call a service. Body = `{entity_id, ...service_data}`. |
| GET  | `/events` | List event types. |
| POST | `/events/{event_type}` | Fire an event. |
| GET  | `/history/period/{ts?}` | Historical state changes. |
| GET  | `/logbook/{ts?}` | Human-readable log of state changes. |

The version-correct schema for any service is always under
`GET /services` → `services.<service>.fields`. Treat
`DOMAIN_CAPABILITIES` as a curated convenience layer, not a substitute.

## Entity ID shape

`{domain}.{object_id}` — for example `light.kitchen`, `switch.fan`,
`sensor.outside_temperature`. The domain selects which services apply.

## Service-call payload

```
POST /api/services/light/turn_on
{
  "entity_id": "light.kitchen",
  "brightness_pct": 80,
  "rgb_color": [255, 180, 100]
}
```

Multiple targets:

```
{"entity_id": ["light.a", "light.b"], "brightness_pct": 50}
```

Newer HA also accepts the structured form:

```
{
  "target": {"entity_id": "light.kitchen"},
  "data":   {"brightness_pct": 80}
}
```

Both work via REST. The code in this project uses the flat form.

## Domain capabilities (curated)

The catalog of common service calls per domain lives in the Python module:
[`backend/app/knowledge/homeassistant.py`](../backend/app/knowledge/homeassistant.py).

Highlights:

- **light** — `turn_on / turn_off / toggle`. `turn_on` accepts
  `brightness` (0–255), `brightness_pct` (0–100), `rgb_color`,
  `color_temp` (mireds), `kelvin`, `transition`, `effect`.
- **switch / input_boolean** — `turn_on / turn_off / toggle`.
- **fan** — `turn_on (percentage)`, `set_percentage`, `oscillate`,
  `set_direction (forward|reverse)`, `set_preset_mode`.
- **climate** — `set_temperature (temperature | target_temp_high/low | hvac_mode)`,
  `set_hvac_mode`, `set_fan_mode`, `set_humidity`, `set_preset_mode`,
  `set_swing_mode`.
- **cover** — `open_cover / close_cover / stop_cover / toggle`,
  `set_cover_position`, plus tilt variants.
- **media_player** — power, volume, transport, `select_source`,
  `play_media`.
- **lock** — `lock / unlock / open` (each accepts optional `code`).
- **alarm_control_panel** — `alarm_arm_home/away/night/vacation`,
  `alarm_disarm`, `alarm_trigger`.
- **scene** — `turn_on` activates; `apply` for ad-hoc.
- **script / automation** — `turn_on / turn_off / toggle`,
  `automation.trigger`, `automation.reload`.
- **vacuum** — `start / pause / stop / return_to_base / locate / clean_spot`,
  `set_fan_speed`, `send_command`.
- **input_number / input_select / input_text / input_button** — helpers
  with `set_value / select_option / press` etc.
- **notify / tts / persistent_notification** — message delivery.
- **sensor / binary_sensor / device_tracker / person / weather / sun /
  zone** — read-only.

For any domain not in the catalog, the universal services
`homeassistant.turn_on`, `turn_off`, `toggle`, `update_entity` usually work.

## Examples

Turn the kitchen light on at 60% warm white:

```http
POST /api/services/light/turn_on
{
  "entity_id":   "light.kitchen",
  "brightness_pct": 60,
  "kelvin":      2700
}
```

Set thermostat to cool at 22 °C:

```http
POST /api/services/climate/set_temperature
{
  "entity_id":   "climate.living_room",
  "temperature": 22,
  "hvac_mode":   "cool"
}
```

Close the garage door:

```http
POST /api/services/cover/close_cover
{ "entity_id": "cover.garage" }
```

Trigger an automation:

```http
POST /api/services/automation/trigger
{ "entity_id": "automation.movie_night" }
```

## Live Agent (forthcoming)

The Live Agent will read `DOMAIN_CAPABILITIES` to:

1. Describe to the LLM what it can do (`description` + `services`).
2. Validate LLM-proposed calls against the parameter shapes (`params` with
   `type`, `range`, `choices`).
3. Translate the validated call into a `POST /api/homeassistant/call` on this
   backend, which forwards to HA.

Any change to capabilities should land in `homeassistant.py` first — the UI
and the agent read from there.
