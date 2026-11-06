# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Minimum supported Home Assistant version raised to 2026.11.0** - the
  integration uses APIs introduced in 2026.11.
- **Repair issues are linked to the integration entry** - they appear on the
  integration's page and Home Assistant removes them together with the entry.
- **Sensors are renamed in place** - changing a sensor's entity ID updates the
  entity instead of removing and re-adding it (Home Assistant 2026.11).
- **Marketplace category and quality tier** - the manifest declares the
  `energy.solar_batteries` category and the Platinum quality scale tier.
- **Validation engine** - forms and actions use probatio, Home Assistant's
  validation engine, instead of voluptuous. No user-visible change.
- **Development tooling** - tests run on `pytest-homeassistant` 2026.11.0, the
  test package published by Home Assistant core.

### Removed

- Local translations of the "credentials were updated" and "connection settings
  were updated" messages: Home Assistant translates them centrally since 2026.10.
