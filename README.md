# FIMER (ABB / Power-One)

<!-- BEGIN SHARED:repo-sync:badges -->
<!-- Synced by repo-sync on 2026-09-04 -->

[![GitHub Release](https://img.shields.io/github/v/release/alexdelprete/ha-fimer?style=for-the-badge)](https://github.com/alexdelprete/ha-fimer/releases)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-donate-yellow?style=for-the-badge&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/alexdelprete)
[![Tests](https://img.shields.io/github/actions/workflow/status/alexdelprete/ha-fimer/test.yml?style=for-the-badge&label=Tests)](https://github.com/alexdelprete/ha-fimer/actions/workflows/test.yml)
[![Coverage](https://img.shields.io/codecov/c/github/alexdelprete/ha-fimer?style=for-the-badge)](https://codecov.io/gh/alexdelprete/ha-fimer)
[![GitHub Downloads](https://img.shields.io/github/downloads/alexdelprete/ha-fimer/total?style=for-the-badge)](https://github.com/alexdelprete/ha-fimer/releases)

<!-- END SHARED:repo-sync:badges -->

The **FIMER (ABB / Power-One)** integration polls an ABB, Power-One, or FIMER solar inverter over
Modbus TCP using the [SunSpec](https://sunspec.org/) information models, and integrates it in your
Home Assistant installation.

It is built on Home Assistant's shared Modbus connection layer
([`modbus-connection`](https://home-assistant-libs.github.io/modbus-connection/)). The integration
asks Home Assistant for a unit on a shared connection instead of opening its own socket, so it can
coexist with any other integration talking to the same inverter or datalogger.

## Supported devices

The integration supports inverters that expose the SunSpec Modbus TCP interface, either directly or
through a VSN300 / VSN700 datalogger card. Behind a datalogger the inverter model is read from the
SunSpec options string, so the device page shows the inverter (for example `PVI-10.0-OUTD`) rather
than the card. Known model codes cover the PVI, TRIO, UNO, UNO-DM and REACT2 families.

The SunSpec models read are:

| Model   | Content                                                                         |
| ------- | ------------------------------------------------------------------------------- |
| 1       | Manufacturer, model, options, firmware version and serial number                |
| 101/103 | Single or three phase inverter: AC and DC readings, energy, temperatures, state |
| 120     | Nameplate: rated power                                                          |
| 121     | Basic settings                                                                  |
| 123     | Immediate controls: the active power limit                                      |
| 160     | Per-input DC current, voltage and power (up to three MPPT inputs)               |
| 64061   | ABB vendor model: Aurora states, alarms, daily to yearly energy, extra readings |

Models the device does not serve are skipped, and readings the inverter reports as not
implemented create no entity. A VSN300 on firmware 2.0.1 in front of a PVI serves models 1,
103, 160, 120, 121 and 123; the ABB vendor model is read when a device exposes it.

## Prerequisites

You should either set a static IP or assign a static DHCP lease for the inverter or datalogger, or
alternatively access it through the local DNS name if your network is configured accordingly.

Modbus TCP must be enabled on the device. On a VSN300 / VSN700 datalogger, open the logger's web
interface and enable the Modbus TCP server. Behind a datalogger the SunSpec map starts at register
`0` and the inverter answers on unit ID `2` (some firmwares use `247`); a natively Modbus inverter
such as a REACT2 uses base address `40000` and unit ID `1`.

The inverter must be awake while you set it up: a PVI without grid power answers nothing at night.

<!-- BEGIN SHARED:repo-sync:installation -->
<!-- Synced by repo-sync on 2026-09-04 -->

## Installation

### HACS (Recommended)

1. Open HACS in your Home Assistant instance
1. Click on "Integrations"
1. Click the three dots menu in the top right corner
1. Select "Custom repositories"
1. Add `https://github.com/alexdelprete/ha-fimer` as an Integration
1. Click "Download" and install the integration
1. Restart Home Assistant

### Manual Installation

1. Download the latest release from [GitHub Releases](https://github.com/alexdelprete/ha-fimer/releases)
1. Extract the `custom_components/fimer` folder
1. Copy it to your Home Assistant `config/custom_components/` directory
1. Restart Home Assistant

<!-- END SHARED:repo-sync:installation -->

## Configuration

The integration is set up from the Home Assistant UI. Go to **Settings** > **Devices & services**,
select **Add integration**, and search for **FIMER (ABB / Power-One)**.

| Parameter            | Required | Description                                                       |
| -------------------- | -------- | ----------------------------------------------------------------- |
| Host                 | yes      | The host name or IP address of the inverter or datalogger.        |
| Port                 | no       | The Modbus TCP port. The default is `502`.                        |
| Modbus unit ID       | no       | The unit (slave) ID the inverter answers on. The default is `2`.  |
| SunSpec base address | no       | The register the SunSpec map starts at. The default is `0`.       |

The unit ID and base address sit under _Advanced settings_ in the form.

The connection is validated during setup by walking the SunSpec model chain and reading the common
model. The inverter's serial number becomes the unique identifier of the config entry, so changing
the host or IP later (through **Reconfigure** on the integration page) does not affect entities or
their history.

The polling interval (10 to 600 seconds, default 30) can be adjusted after setup from the
integration's options.

## Monitored data

The integration reads the SunSpec models the device exposes and creates a sensor for every reading
the inverter implements. Readings that appear later, for instance once the inverter is producing,
get their sensor on the next poll.

- Inverter (models 101/103)

  AC power, current and voltage split among the phases on three phase inverters, frequency,
  apparent and reactive power, power factor, total energy, DC power, current and voltage, cabinet
  and other temperatures, and the SunSpec operating state.

- MPPT inputs (model 160)

  `DC current input <n>`, `DC voltage input <n>` and `DC power input <n>` for each input the
  inverter reports. Per-input energy is exposed only on inverters that implement it.

- Ratings and controls (models 120 and 123)

  The rated power, the active power limit in percent and whether it is enabled, as diagnostic
  entities.

- Aurora states and vendor readings (model 64061, where the device serves it)

  Global, inverter and DC input states with their Aurora names, the active alarms, energy today,
  this week, this month and this year, inverter and booster temperatures, isolation resistance,
  cos phi, the permanent and dynamic power limits and the inverter's clock. The vendor lifetime
  and partial counters are available but disabled by default.

When the inverter is powered down at night, its measurements become unavailable. Energy counters
keep their last value, restored across restarts, so long-term statistics and the energy dashboard
keep their history. Connection loss is handled automatically: the shared connection reconnects on
the next poll and the integration does not reload. After three failed polls in a row the inverter
is polled every five minutes until it answers again.

## Energy dashboard

Recommended [energy dashboard](https://www.home-assistant.io/docs/energy/) configuration:

- For _"Solar production"_, add the inverter's `Total energy` entity. That is the AC energy you can
  use or sell.

Where the inverter reports per-input energy, `DC energy input <n>` is what the panels delivered
before conversion losses, so it reads a few percent higher. Prefer the AC value.

## Example automation

The following automation toggles a switch when the solar production crosses certain thresholds:

```yaml
description: "Turn on switch when PV power is above 1000 W and turn it off below 50 W."
mode: single
triggers:
  - trigger: state
    entity_id:
      - sensor.pvi_10_0_outd_ac_power
conditions: []
actions:
  - choose:
      - conditions:
          - condition: numeric_state
            entity_id: sensor.pvi_10_0_outd_ac_power
            above: 1000
        sequence:
          - action: switch.turn_on
            target:
              entity_id: switch.my_load
      - conditions:
          - condition: numeric_state
            entity_id: sensor.pvi_10_0_outd_ac_power
            below: 50
        sequence:
          - action: switch.turn_off
            target:
              entity_id: switch.my_load
```

## Known limitations

The integration is read-only. It exposes what the SunSpec models implement on the device and does
not write to the inverter. The SunSpec immediate controls model is read, but on the hardware tested
so far (a PVI-10.0-OUTD behind a VSN300 on firmware 2.0.1) the datalogger stores a power limit
written to it without the inverter acting on it, so no control entity is offered.

The SunSpec register map of a device can change with a firmware update or when a datalogger is
reconfigured. The integration verifies the model headers on every poll and re-discovers the models
in place when the map moves.

The ABB vendor model (64061) is read according to the 2013 Power-One register map, which reports a
model length of 124. A device serving a different length has its vendor model skipped, with a
warning in the log; please open an issue with the diagnostics download so the layout can be added.

Details about Modbus registers can be found in the device documentation or on the
[FIMER website](https://www.fimer.com/).

## Troubleshooting

### Can't set up the device

- Make sure the inverter is awake: without grid power at night it does not answer at all.
- Make sure the device is connected to the network and is reachable from the Home Assistant instance.
- Check the device's settings to ensure that Modbus TCP is enabled and the unit ID is correct.
- If no SunSpec map is found, try base address `0` behind a VSN card or `40000` on a natively
  Modbus inverter, under _Advanced settings_.
- If another integration already uses the same host with different link settings, Home Assistant
  reports a conflict. One connection cannot honour two configurations at once.

### Some entities are missing after setup

Some data is only provided by the inverter when it is producing. When the integration is added at
night, some entities may be added at sunrise when the inverter begins to answer.

### Entities are unavailable

- Make sure the inverter is not in a power-saving mode. An inverter that is powered down does not
  answer, and the entities come back on the next successful poll.
- Download the diagnostics from the device page. They contain the raw register map the integration
  reads, which is the most useful thing to attach to a bug report.

## Removing the integration

This integration can be removed by following these steps:

1. Go to **Settings** > **Devices & services**.
1. Select **FIMER (ABB / Power-One)**.
1. Open the three dots menu of the config entry and select **Delete**.

<!-- BEGIN SHARED:repo-sync:contributing -->
<!-- Synced by repo-sync on 2026-09-04 -->

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
1. Create a feature branch (`git checkout -b feature/my-feature`)
1. Make your changes
1. Run linting: `pre-commit run --all-files`
1. Commit your changes (`git commit -m "feat: add my feature"`)
1. Push to your branch (`git push origin feature/my-feature`)
1. Open a Pull Request

Please ensure all CI checks pass before requesting a review.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development environment (devcontainer, tests, live
Home Assistant instance) and the Windows caveats.

<!-- END SHARED:repo-sync:contributing -->

<!-- BEGIN SHARED:repo-sync:license -->
<!-- Synced by repo-sync on 2026-09-04 -->

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

<!-- END SHARED:repo-sync:license -->
