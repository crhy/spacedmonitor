# Spaced Monitor 0.1.10

Approved source version: `0.1.10`. This does not change the Spaced Linux
release version. Install the local package with:

```sh
sudo apt install './build/spaced-monitor_0.1.10_all.deb'
```

## Changes to test

- Overview order is CPU, system memory, then each GPU beside its VRAM card.
  Temperature labels are reduced to 100/140/180°F at the default range; the
  bottom clock labels are removed, reclaiming their space for the plot.

- Larger overview gauges, streamlined memory cards and a horizontal CPU/GPU
  temperature legend. Temperature defaults to Fahrenheit. The °F/°C toggle beside
  About and the theme toggle updates all views and histories and persists per user.
- Each VRAM More button opens its own device-specific, enlarged memory card.
  NVIDIA compute and graphics process allocations are shown in MiB when the
  driver exposes them. Unsupported devices explicitly show unavailable.
- Suggest measures recent CPU, RAM, GPU, VRAM and physical-drive activity. After
  at least five samples it identifies the highest sustained pressure candidate.
  Busy non-NVMe drives can suggest NVMe after checking workload and compatibility;
  idle systems do not receive speculative upgrade recommendations. This is not a
  benchmark or proof of a hardware bottleneck.
- Default client size is 850 × 620 pixels, approximately the supplied screenshot.
  The three-GPU overview fits without scrolling at normal font size; smaller
  windows, larger fonts and additional devices can scroll without hiding readings.
- Every overview/hardware card has a bottom-right More button. Device views now
  include gauges for numeric readings (including individual CPU threads and RAM
  temperatures), with explicit units and scales. Identity fields remain text.
- GPUs retain driver enumeration order, placing the primary RTX 4070 Ti SUPER
  before the RTX 3050 and integrated AMD GPU on the test machine.

- Compact Hardware rows with expandable quick details; expansion persists during
  refreshes and theme changes.
- Double-click a hardware/overview card for a full-window device view. More
  buttons provide a keyboard-accessible alternative. Back or Escape returns.
  Selectable text and interactive controls keep their normal behavior.
- CPU details include physical cores, logical-thread activity, reported clock
  range, package power and available temperature sensors.
- RAM temperatures use kernel-exposed memory sensors only. Unsupported readings
  say unavailable; sensor identities are not guessed DIMM slot numbers. No SMBus
  scanning or privileged probing is performed.
- Separate cards/details for each detected GPU, keyed by device identity rather
  than model name. Mixed NVIDIA/AMD devices and missing measurements are supported.
- Two-minute device histories and resettable session maxima. Removed devices
  show unavailable without switching to a different device.
- Missing GPU utilization no longer appears as zero. Stopped fans remain visible
  at zero RPM. Arbitrary motherboard readings are not presented as CPU temperature.

Check narrow windows, larger desktop fonts, light/dark themes, selection/copy,
Back/Escape navigation, repeated opening/closing, and all GPUs on your machine.
Compare RAM values against the same kernel hwmon sensors. NVIDIA NVML memory
usage can include driver-reserved memory and differ from `nvidia-smi` usage.
Other GPU metrics depend on what the driver exposes. The existing process table
retains its full-window focus behavior, rather than becoming a hardware view.

Run the full automated gate with `bash scripts/check.sh`. It exercises unit tests,
headless UI navigation, live sampling/layout, lifecycle, themes and package checks.
Source push approved after local RC3 testing on 2026-11-20. Package publication
and distro artifact pins must use matching, verified bytes; a source push alone
does not make this version available through APT.
