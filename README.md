# WinTax for Home Assistant

Custom integration for the [WinTax](https://www.wintax.nl/) customer portal used by UVO Vervoer. It logs in through the real `.wts` HTML interface, parses the rides table, and exposes the current or next ride to Home Assistant.

This integration is **read-only**. It does not cancel rides, change bookings, export data, or configure 2FA.

## Install

1. Copy `custom_components/wintax` into your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and search for **WinTax**.
4. Enter your WinTax username and password. Optionally set the update interval (default 60 seconds, minimum 30).

Credentials are stored in a Home Assistant config entry. They are never written into Python source files.

You can also add this repository as a custom HACS integration if you use HACS.

## Entities

| Entity | When it exists | State |
| --- | --- | --- |
| `sensor.wintax_next_ride` | Always | WinTax status (`Onderweg naar klant`, `Automatisch verzenden`, …) or `Gepland` / `Geen ritten` |
| `sensor.wintax_next_ride_start` | Always | Planned or actual start (timestamp) |
| `sensor.wintax_next_ride_end` | Always | Planned or actual end (timestamp) |
| `sensor.wintax_ride_status` | Always | Exact WinTax status chip, if present |
| `binary_sensor.wintax_tracking_available` | Always | `on` only when the selected ride has a tracking link **and** usable GPS data |
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
