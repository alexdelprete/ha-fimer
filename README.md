# FIMER (ABB / Power-One)

<!-- BEGIN SHARED:repo-sync:badges -->
<!-- Synced by repo-sync on 2026-09-04 -->

[![GitHub Release](https://img.shields.io/github/v/release/alexdelprete/ha-fimer?style=for-the-badge)](https://github.com/alexdelprete/ha-fimer/releases)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-donate-yellow?style=for-the-badge&logo=buy-me-a-coffee)](https://www.buymeacoffee.com/alexdelprete)
[![Tests](https://img.shields.io/github/actions/workflow/status/alexdelprete/ha-fimer/test.yml?style=for-the-badge&label=Tests)](https://github.com/alexdelprete/ha-fimer/actions/workflows/test.yml)
[![Coverage](https://img.shields.io/codecov/c/github/alexdelprete/ha-fimer?style=for-the-badge)](https://codecov.io/gh/alexdelprete/ha-fimer)
[![GitHub Downloads](https://img.shields.io/github/downloads/alexdelprete/ha-fimer/total?style=for-the-badge)](https://github.com/alexdelprete/ha-fimer/releases)

<!-- END SHARED:repo-sync:badges -->

The **FIMER (ABB / Power-One)** integration reads FIMER, ABB and Power-One solar inverters and the
VSN300 / VSN700 datalogger cards in front of them, and integrates them in your Home Assistant
installation. It has two sources, each optional:

- **Modbus TCP** with the [SunSpec](https://sunspec.org/) information models, for the inverter's
  live readings, energy and states.
- The datalogger's **REST API**, for the card itself, the periodic energy counters, and the meters
  and batteries a VSN700 manages.

Both sources report the same readings under the same names, so an entity does not care which one
delivered its value. Modbus is built on Home Assistant's shared Modbus connection layer
([`modbus-connection`](https://home-assistant-libs.github.io/modbus-connection/)): the integration
asks Home Assistant for a unit on a shared connection instead of opening its own socket, so it can
coexist with any other integration talking to the same inverter or datalogger.

## Supported devices

Inverters of the PVI, TRIO, UNO, UNO-DM and REACT2 families, read either directly (natively Modbus
inverters such as the REACT2) or through a VSN300 or VSN700 datalogger card. Behind a datalogger the
inverter model is decoded from the SunSpec options string, so the device page shows the inverter
(for example `PVI-10.0-OUTD`) rather than the card. Meters and batteries connected to a VSN700 are
read over its REST API.

The SunSpec models read over Modbus are:

| Model       | Content                                                                         |
| ----------- | ------------------------------------------------------------------------------- |
| 1           | Manufacturer, model, options, firmware version and serial number                |
| 101/103     | Single or three phase inverter: AC and DC readings, energy, temperatures, state |
| 111/113     | The same, on inverters that serve the float variants                            |
| 120         | Nameplate: rated power                                                          |
| 121         | Basic settings                                                                  |
| 123         | Immediate controls: the active power limit                                      |
| 124         | Basic storage controls, on REACT2 hybrids                                       |
| 160         | Per-input DC current, voltage and power (up to three MPPT inputs)               |
| 403         | String combiners, one per DC input of a TRIO                                    |
| 64061       | ABB vendor model: Aurora states, alarms, daily to yearly energy, extra readings |
| 64062/64063 | TRIO communication and fuse control boards                                      |

Models the device does not serve are skipped, and readings the inverter reports as not
implemented create no entity. A VSN300 on firmware 2.0.1 in front of a PVI serves models 1, 103,
160, 120, 121 and 123; the TRIO models come from the manufacturer's register map and have not
been seen on hardware yet.

## Prerequisites

You should either set a static IP or assign a static DHCP lease for the inverter or datalogger, or
alternatively access it through the local DNS name if your network is configured accordingly.

For Modbus, Modbus TCP must be enabled on the device. On a VSN300 / VSN700 datalogger, open the
logger's web interface and enable the Modbus TCP server. Behind a datalogger the SunSpec map starts
at register `0` and the inverter answers on unit ID `2` (some firmwares use `247`); a natively
Modbus inverter such as a REACT2 uses base address `40000` and unit ID `1`.

For the REST API you need the card's credentials: the user is usually `guest`, the password the one
set on the card, which may be empty. A VSN300 on firmware 2.0.0 cannot serve live data because of a
firmware defect; update it to 2.0.1 or later.

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

| Parameter                     | Required | Description                                                        |
| ----------------------------- | -------- | ------------------------------------------------------------------ |
| Host                          | yes      | The host name or IP address of the inverter or datalogger.         |
| Port                          | no       | The Modbus TCP port. The default is `502`.                         |
| Read over Modbus TCP          | no       | Enable the Modbus source. On by default.                           |
| Modbus unit ID                | no       | The unit (slave) ID the inverter answers on. The default is `2`.   |
| SunSpec base address          | no       | The register the SunSpec map starts at. The default is `0`.        |
| Read the datalogger REST API  | no       | Enable the REST source. Off by default.                            |
| Username                      | no       | The card's user. The default is `guest`.                           |
| Password                      | no       | The password set on the card, if any.                              |

The Modbus settings sit in the **Modbus TCP (SunSpec)** section of the form, the REST settings in the
**Datalogger REST API** section. At least one source must be enabled. Each is validated during
setup: Modbus by walking the SunSpec model chain, REST by identifying the card and reading its
devices.

When both sources are enabled, a reading available from both comes from Modbus, and REST fills in
whatever Modbus lacks or while Modbus is down. Each physical device becomes one Home Assistant
device: the inverter, the datalogger, and any meter or battery, linked through the datalogger.

The inverter's serial number becomes the unique identifier of the config entry (the datalogger's
when no inverter is found), so changing the host, the credentials or the sources later, through
**Reconfigure** on the integration page, does not affect entities or their history.

### Taking over the ABB/FIMER PVI VSN REST integration

If the earlier `abb_fimer_pvi_vsn_rest` integration is installed, the setup starts with a choice
to take over one of its entries. Its host and credentials are prefilled and, when the new entry
loads, the old entry is removed and its sensors are re-registered here with their entity IDs,
names, icons and areas, so recorded history and long-term statistics continue. The takeover is
one-way: removing this integration later does not bring the old entry back.

### Options

Open the integration's **Options** to change:

| Option                              | Default | Description                                                        |
| ----------------------------------- | ------- | ------------------------------------------------------------------ |
| Update interval                     | `30` s  | Seconds between polls, 10 to 600, for both sources.                |
| Power limit control (experimental)  | off     | Expose the SunSpec power limit as a number and a switch, see below. |

The entry reloads when options are saved.

## Monitored data

A sensor is created for every reading a device reports, from whichever source reports it.
Readings that appear later, for instance once the inverter is producing, get their sensor on the
next poll.

- Inverter, over Modbus (models 101/103 or 111/113)

  AC power, current and voltage split among the phases on three phase inverters, frequency,
  apparent and reactive power, power factor, total energy, DC power, current and voltage, cabinet
  and other temperatures, the SunSpec operating state and active events.

- MPPT inputs, over Modbus (model 160)

  `DC current input <n>`, `DC voltage input <n>` and `DC power input <n>` for each input the
  inverter reports. Per-input energy is exposed only on inverters that implement it.

- Ratings and controls, over Modbus (models 120 and 123)

  The rated power, the active power limit in percent and whether it is enabled, as diagnostic
  entities. REACT2 hybrids add the storage model's charge state, battery voltage and rate limits.

- Aurora states and vendor readings (the ABB vendor model over Modbus, or the REST API)

  Global, inverter and DC input states with their Aurora names, the alarm state and active alarms,
  energy today, this week, this month and this year, inverter and booster temperatures, isolation
  resistance, cos phi, the permanent and dynamic power limits and the inverter's clock. The vendor
  lifetime and partial counters are available but disabled by default.

- Inverter extras, over the REST API

  Bulk capacitor and midpoint voltages, ground voltage, leakage currents, peak power lifetime and
  today, per-phase frequencies, per-string energies, the periodic counters for absorbed, apparent,
  self-consumed and backup energy, fan speeds, derating flags and the digital inputs, as the card
  reports them for the inverter model.

- Datalogger, over the REST API

  Card type, serial and part number, firmware, uptime, load, free memory and flash, WiFi mode,
  SSID, address, link quality and connection state.

- Meter, over the REST API of a VSN700

  Grid voltage, current, power and reactive power per phase and in total, frequency, house
  consumption per phase, and the energy counters for grid import and export and house consumption,
  lifetime and periodic.

- Battery, over the REST API of a VSN700

  State of charge and health, voltage, current and power, cell voltage and temperature extremes,
  charge and discharge cycles, and the charge and discharge energies, lifetime and periodic.

When the inverter is powered down at night, its measurements become unavailable. Energy counters
keep their last value, restored across restarts, so long-term statistics and the energy dashboard
keep their history. Connection loss is handled automatically: the shared Modbus connection
reconnects on the next poll and the integration does not reload. After three failed polls in a
row a source is polled every five minutes until it answers again; the other source keeps its own
schedule.

## Energy dashboard

Recommended [energy dashboard](https://www.home-assistant.io/docs/energy/) configuration:

- For _"Solar production"_, add the inverter's `Total energy` entity. That is the AC energy you can
  use or sell.
- With a meter behind a VSN700, add the meter's `Energy AC - Grid Import (Lifetime)` and
  `Energy AC - Grid Export (Lifetime)` entities for _"Grid consumption"_ and _"Return to grid"_.
- With a battery behind a VSN700, add its `Energy - Battery Charge (Lifetime)` and
  `Energy - Battery Discharge (Lifetime)` entities under _"Battery systems"_.

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

## Power limit control (experimental)

The SunSpec immediate controls model (123) carries an active power limit in percent of the rated
power and a flag that enables it. The integration can expose them as a `Power limit` number and
switch, off by default: enable **Power limit control (experimental)** in the integration's options.
The entities appear only when the inverter serves model 123.

Whether the inverter acts on the limit depends on the inverter, not on the datalogger. A VSN300
accepts the writes for every inverter, answers them with a Modbus negative acknowledge, and reads
back the values written. Inverters of the Aurora protocol generation (the PVI, TRIO and UNO
families with firmware from before about 2014) have no power-reduction command at all: their only
remote control is the hardware "Remote ON/OFF" input, so they ignore the SunSpec limit, as verified
on a PVI-10.0-OUTD. Newer inverters such as the REACT2 and UNO-DM-PLUS families are expected to
honour it, but this has not been verified yet. If you try it, please run this test and report the
outcome in an issue:

1. Note the AC power while the inverter is producing well above 10 % of its rated power.
1. Set `Power limit` to 10 and switch it on. Watch the AC power for three minutes; the datalogger
   refreshes its readings about once a minute.
1. Switch the limit off and check that production recovers within a few minutes.

Report the inverter model and firmware (both shown on the device page), the datalogger model and
firmware, whether the AC power followed the limit, and attach the diagnostics download.

## Actions

The integration provides these actions, all addressed to a config entry. The register and point
actions need the Modbus source; the others work with either source.

- `fimer.read_registers`: read holding or input registers at an absolute address and decode them
  as a 16- or 32-bit integer, a float or a string. Returns the raw registers and the decoded value.
- `fimer.write_registers`: write one value encoded as a chosen type, or a list of raw registers, at
  an absolute address.
- `fimer.write_point`: write a writable SunSpec point by name, for example `WMaxLimPct`, in its
  engineering unit.
- `fimer.set_power_limit`: set the active power limit in percent and whether it is applied,
  verified by reading back.
- `fimer.get_readings`: return every point each device of the entry currently reports, with the
  device type and availability.
- `fimer.rediscover`: walk the SunSpec chain and the datalogger's devices again without a reload,
  and refresh both sources. The entry is reloaded only when new devices appeared.

Register writes go straight to the device: use them only with the register map at hand. An
example reading the power limit register of model 123 on a VSN300 (header at 232, limit at
offset 5):

```yaml
action: fimer.read_registers
data:
  config_entry: 01ABCDEF0123456789ABCDEF01
  address: 237
  data_type: uint16
response_variable: limit
```

## Known limitations

The integration is read-only unless the experimental power limit control is switched on (see
above). On the hardware tested so far, a PVI-10.0-OUTD behind a VSN300 on firmware 2.0.1, the
datalogger stores the power limit written to it without the inverter acting on it.

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
  Modbus inverter, in the Modbus section of the form.
- If another integration already uses the same host with different link settings, Home Assistant
  reports a conflict. One connection cannot honour two configurations at once.
- If the REST API rejects the username or password, check them in the card's web interface; the
  user is usually `guest`.
- If no REST API answers at the host, the device is not a VSN300 / VSN700 card, or its REST server
  is disabled.
- A VSN300 on firmware 2.0.0 is refused: update the card to 2.0.1 or later.

### Some entities are missing after setup

Some data is only provided by the inverter when it is producing. When the integration is added at
night, some entities may be added at sunrise when the inverter begins to answer. Meters, batteries
and the datalogger's own sensors need the REST source enabled.

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

Deleting the entry removes its devices and entities. If the entry took over an earlier REST entry,
that one is not restored.

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
