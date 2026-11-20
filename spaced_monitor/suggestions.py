"""Read-only disk activity and conservative, short-window pressure hints.

io_ticks describes time with I/O active, not a throughput ceiling:
https://www.kernel.org/doc/html/latest/block/stat.html
"""
from collections import deque
from pathlib import Path
import time


class DiskActivity:
    def __init__(self, root="/sys/block", clock=time.monotonic):
        self.root, self.clock, self.previous = Path(root), clock, {}

    def sample(self):
        now = self.clock()
        result, current = [], {}
        for device in self.root.glob("*"):
            if device.name.startswith(("loop", "ram", "zram", "dm-", "md", "sr")):
                continue
            try:
                stats = [int(v) for v in (device / "stat").read_text().split()]
                ticks = stats[9]
                rotational = (device / "queue/rotational").read_text().strip() == "1"
            except (OSError, ValueError, IndexError):
                continue
            old = self.previous.get(device.name)
            current[device.name] = (now, ticks)
            busy = None
            if old and now > old[0] and ticks >= old[1]:
                busy = min(100, (ticks - old[1]) / (now - old[0]) / 10)
            kind = "NVMe" if device.name.startswith("nvme") else "HDD" if rotational else "SSD / non-NVMe"
            result.append((device.name, kind, busy))
        self.previous = current
        return result


class Suggestions:
    def __init__(self):
        self.samples = deque(maxlen=20)

    def update(self, snap):
        readings = {"CPU": snap.cpu.percent,
                    "RAM": ((1 - snap.memory.available / snap.memory.total) * 100
                            if snap.memory.total else None)}
        for g in snap.gpus or ([snap.gpu] if snap.gpu else []):
            readings[f"GPU · {g.name} · {g.device_id}"] = g.percent
            readings[f"VRAM · {g.name} · {g.device_id}"] = (g.mem_used / g.mem_total * 100
                if g.mem_total and g.mem_used is not None else None)
        for name, kind, busy in snap.disk_devices:
            readings[f"Drive · {name} · {kind}"] = busy
        self.samples.append(readings)

    def rows(self):
        if len(self.samples) < 5:
            return [("Measuring", "Run your normal workload; collecting at least five samples before suggesting anything.")]
        latest = self.samples[-1]
        averages = {}
        for key in latest:
            vals = [s[key] for s in self.samples if s.get(key) is not None]
            if len(vals) >= 5:
                averages[key] = sum(vals) / len(vals)
        ranked = sorted(averages.items(), key=lambda item: item[1], reverse=True)
        candidates = [(k, v) for k, v in ranked if v >= (90 if k.startswith(("RAM", "VRAM")) else 80)]
        rows = [("Assessment", f"Average of up to {len(self.samples)} recent samples. High activity is a bottleneck candidate, not proof that hardware needs replacing.")]
        if not candidates:
            rows.append(("Biggest bottleneck", "No sustained high pressure detected. Run the workload that feels slow and check again."))
        else:
            key, value = candidates[0]
            rows.append(("Highest observed pressure", f"{key}: {value:.0f}%"))
            if key.startswith("Drive"):
                advice = ("This drive is busy most of the sampled time. If file loads or transfers are slow, an NVMe SSD may help. Check motherboard slot support and the workload's actual drive before buying."
                          if "NVMe" not in key.replace("non-NVMe", "") else
                          "The NVMe drive is frequently active. Check competing disk users and free space before considering a faster drive.")
            elif key.startswith("VRAM"):
                advice = "Video memory is nearly full. Use the GPU memory More view to identify allocations; reduce model, texture or batch size before considering more VRAM."
            elif key == "RAM":
                advice = "Available RAM is low. Check Processes for memory-heavy apps. More RAM may help if the workload also swaps or stalls."
            elif key == "CPU":
                advice = "CPU usage is sustained. Check Processes and CPU More for heavy apps and individual threads; reduce background work before considering a CPU upgrade."
            else:
                advice = "The GPU is busy. This can be expected during rendering or compute. Lower workload settings or check competing GPU tasks before considering an upgrade."
            rows.append(("Suggestion", advice))
        rows.extend((key, f"{value:.0f}% average {'active time' if key.startswith('Drive') else 'usage'}") for key, value in ranked)
        rows.append(("Limits", "Not a benchmark. Disk active time is not bandwidth saturation; full VRAM may be intentional caching. Network capacity, per-thread limits and thermal throttling are not diagnosed here."))
        return rows
