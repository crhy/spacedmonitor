# Spaced Monitor

The system monitor for Spaced Linux: CPU, GPU, memory, temperatures, disks, network and
the programs using them, in one window that is easy to read at a glance. Rich colours on
the gauges, clear temperature graphs, dark and light themes.

Status: in development ([crhy/spaced#385](https://github.com/crhy/spaced/issues/385)).

![Overview mockup](docs/mockup-overview.png)

## Planned

- **Overview**: CPU, GPU, memory and GPU-memory gauges; a five-minute CPU/GPU temperature
  graph; disk and network activity; "What is using your computer?" with per-program CPU,
  RAM, GPU and disk use, and a button to end a program; fans, CPU/GPU power and uptime.
- **Processes**: the full process list, searchable and sortable.
- **Hardware**: per-core, per-sensor and per-device detail.

Native Debian package (Python, GTK 3), shipped through the Spaced Linux APT repository.
No systemd. GPL-3.0-or-later.
