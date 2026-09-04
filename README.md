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

<!--
TODO: The device list, entity list, and control section below are placeholders until the
device library is modelled against real register maps. Confirm every device before release.
-->

## Supported devices

The integration supports inverters that expose the SunSpec Modbus TCP interface, either directly or
through a VSN300 / VSN700 datalogger card. This includes among others:

- PVI-3.0 / 3.6 / 4.2 / 5000 / 6000-TL-OUTD
- PVI-10.0 / 12.5-TL-OUTD
- TRIO
- UNO-DM
- REACT

Devices connected to the same datalogger are supported as well, one Modbus unit ID per inverter.

## Prerequisites

You should either set a static IP or assign a static DHCP lease for the inverter or datalogger, or
alternatively access it through the local DNS name if your network is configured accordingly.

Modbus TCP must be enabled on the device. On a VSN300 / VSN700 datalogger, open the logger's web
interface and enable the Modbus TCP server; note the port and the unit ID assigned to each
inverter.

<!-- TODO: Exact menu path per device family, and the default unit ID (often 2 behind a VSN300). -->

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

| Parameter     | Required | Description                                                                 |
| ------------- | -------- | --------------------------------------------------------------------------- |
| Host          | yes      | The host name or IP address of the inverter or datalogger.                  |
| Port          | no       | The Modbus TCP port. The default is `502`.                                  |
| Unit ID       | yes      | The Modbus unit ID (slave address) of the inverter.                         |

The connection is validated during setup by reading the SunSpec common model. The inverter's serial
number becomes the unique identifier of the config entry, so changing the host or IP later does not
affect entities or their history.

The polling interval can be adjusted after setup from the integration's options.

## Monitored data

The integration reads the SunSpec models the device exposes and creates entities for the values it
implements. Values the device reports as "not implemented" do not create entities.

- Inverter

  AC power, current, voltage and frequency, split among the phases where supported, apparent and
  reactive power, power factor, lifetime energy, DC power, current and voltage, cabinet and heat sink
  temperatures, operating state, and vendor state and event flags.
  Updated every minute by default.

- MPP trackers

  `MPPT <n> DC power`, `MPPT <n> DC current`, `MPPT <n> DC voltage`, and `MPPT <n> energy` for each
  MPP tracker the inverter reports. Current and voltage are disabled by default.

- Nameplate and settings

  Rated power and the device limits, as diagnostic entities. Updated every hour.

<!-- TODO: Add the ABB vendor-specific models once identified on real hardware. -->

When the inverter is powered down at night, its entities become unavailable. Lifetime energy
counters keep their last value, so long-term statistics and the energy dashboard keep their history.
Connection loss is handled automatically: the shared connection reconnects on the next poll and the
integration does not reload.

## Energy dashboard

Recommended [energy dashboard](https://www.home-assistant.io/docs/energy/) configuration:

- For _"Solar production"_, add the inverter's `Total energy` entity. That is the AC energy you can
  use or sell.

Where the device reports per-string energy, `MPPT <n> energy` is what the panels delivered before
inverter conversion losses, so it reads a few percent higher. Prefer the AC value.

## Example automation

The following automation toggles a switch when the solar production crosses certain thresholds:

```yaml
description: "Turn on switch when PV power is above 1000 W and turn it off below 50 W."
mode: single
triggers:
  - trigger: state
    entity_id:
      - sensor.pvi_10_0_ac_power
conditions: []
actions:
  - choose:
      - conditions:
          - condition: numeric_state
            entity_id: sensor.pvi_10_0_ac_power
            above: 1000
        sequence:
          - action: switch.turn_on
            target:
              entity_id: switch.my_load
      - conditions:
          - condition: numeric_state
            entity_id: sensor.pvi_10_0_ac_power
            below: 50
        sequence:
          - action: switch.turn_off
            target:
              entity_id: switch.my_load
```

## Known limitations

The integration is read-only. It exposes what the SunSpec models implement on the device and does
not write to the inverter.

The SunSpec register map of a device can change with a firmware update or when a datalogger is
reconfigured. The integration verifies the model headers on every poll and reloads itself to rescan
when the map moves.

Details about Modbus registers can be found in the device documentation or on the
[FIMER website](https://www.fimer.com/).

## Troubleshooting

### Can't set up the device

- Make sure the device is not in a power-saving mode when currently not producing energy.
- Make sure the device is connected to the network and is reachable from the Home Assistant instance.
- Check the device's settings to ensure that Modbus TCP is enabled and the unit ID is correct.
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
