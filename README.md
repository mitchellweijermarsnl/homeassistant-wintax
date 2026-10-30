# WinTax for Home Assistant

Custom integration for the [WinTax](https://www.wintax.nl/) customer portal used by UVO Vervoer. It logs in through the real `.wts` HTML interface, parses the rides table, and exposes the current or next ride to Home Assistant.

This integration is **read-only**. It does not cancel rides, change bookings, export data, or configure 2FA.

## Install

### HACS (recommended)

1. In HACS go to **Custom repositories**.
2. Add `mitchellweijermarsnl/homeassistant-wintax` as category **Integration** (not plugin, theme, or add-on).
3. Download **WinTax**, then restart Home Assistant.
4. Go to **Settings → Devices & services → Add integration** and search for **WinTax**.

If a previous add failed with `custom_components/None/manifest.json`, remove the custom repository first, restart Home Assistant, then add it again as **Integration**.

### Manual

1. Copy `custom_components/wintax` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and search for **WinTax**.
4. Enter your WinTax username and password.

Credentials are stored in a Home Assistant config entry. They are never written into Python source files.

Polling is limited to **weekdays** in two windows (Europe/Amsterdam):

- 06:30–08:30
- 14:00–15:30

During those windows the portal is queried every **10 seconds**. Outside those times there are no WinTax requests. Change the windows under **Settings → Devices & services → WinTax → Configure**. The same screen sets how many days of rides are fetched (1 day back, 14 days ahead) and how long a ride that WinTax still marks as on the way stays selected after its end time (45 minutes).

## Near home

**Configure → Near home** opens a map with your home pin and a radius. The vehicle counts as near home when its GPS position is inside that circle. Until you save the map, the pin and radius follow Home Assistant's home zone (100 m if that zone has no radius).

The circle is stored on the WinTax integration. The Home Assistant map still uses your home zone for the tracker's `home` / `not_home` state, so the bus can count as near home before it enters the smaller home zone.

## Entities

| Entity | When it exists | State |
| --- | --- | --- |
| `sensor.wintax_next_ride` | Always | WinTax status (`Onderweg naar klant`, `Automatisch verzenden`, …) or `Gepland` / `Geen ritten` |
| `sensor.wintax_next_ride_start` | Always | Planned or actual start (timestamp) |
| `sensor.wintax_next_ride_end` | Always | Planned or actual end (timestamp) |
| `sensor.wintax_ride_status` | Always | Exact WinTax status chip, if present |
| `binary_sensor.wintax_tracking_available` | Always | `on` only when the selected ride has a tracking link **and** usable GPS data |
| `binary_sensor.wintax_near_home` | Always | `on` when the vehicle GPS position is inside the home circle. Unavailable without GPS |
| `sensor.wintax_distance_home` | Always | Distance to the home pin, in meters. Unavailable without GPS |
| `device_tracker.wintax_vehicle` | Only if `map.wts` returns GPS coordinates | Vehicle latitude / longitude |

The selected ride is, in order: the currently active ride, else the next upcoming ride, else the most recent ride.

Ride attributes include trip id, times, origin, destination, passenger **count**, and tracking availability. Passenger names are not exposed.

## Troubleshooting

### Could not connect to the WinTax portal

The portal listens on **TCP port 40083**. Home Assistant must be allowed to reach `uvovervoer.customer.wintax.nl:40083`.

The server also sends an incomplete TLS certificate chain. This integration ships the missing Sectigo intermediate and retries if verification still fails. After updating the integration, restart Home Assistant and try again.

Enable debug logging to see the underlying error (session ids are redacted):

```yaml
logger:
  logs:
    custom_components.wintax: debug
```

## Tests

From the repository root (requires `beautifulsoup4` and `pytest`):

```bash
python3 -m pip install pytest beautifulsoup4
python3 -m pytest
```

## Privacy

Passwords, session ids, cookies, and raw HTML are not logged. Request URLs are redacted before any debug logging.

## License

Use this only with a WinTax account you are authorized to access.
