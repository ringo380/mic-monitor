#!/opt/homebrew/bin/python3
"""Live mic monitor: route an input device to an output device with low latency.

Default: Yeti mic -> Corsair headset, so you hear yourself in the headphones.
"""
import argparse
import signal
import sys

import sounddevice as sd


def find_device(name, kind):
    """kind: 'input' or 'output'. Returns first device index whose name contains `name`."""
    want = name.lower()
    chan_key = "max_input_channels" if kind == "input" else "max_output_channels"
    for i, d in enumerate(sd.query_devices()):
        if want in d["name"].lower() and d[chan_key] > 0:
            return i
    raise SystemExit(f"No {kind} device matching '{name}'. Run with --list to see devices.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="Yeti", help="input device name substring")
    ap.add_argument("--out", dest="out", default="CORSAIR", help="output device name substring")
    ap.add_argument("--gain", type=float, default=1.0, help="output gain multiplier")
    ap.add_argument("--blocksize", type=int, default=256, help="frames/block (lower=less latency)")
    ap.add_argument("--samplerate", type=int, default=48000)
    ap.add_argument("--list", action="store_true", help="list devices and exit")
    args = ap.parse_args()

    if args.list:
        print(sd.query_devices())
        return

    in_idx = find_device(args.inp, "input")
    out_idx = find_device(args.out, "output")
    in_name = sd.query_devices(in_idx)["name"]
    out_name = sd.query_devices(out_idx)["name"]
    gain = args.gain

    def callback(indata, outdata, frames, time, status):
        if status:
            print(status, file=sys.stderr)
        if gain != 1.0:
            outdata[:] = indata * gain
        else:
            outdata[:] = indata

    print(f"Monitoring: {in_name}  ->  {out_name}")
    print(f"gain={gain}  blocksize={args.blocksize}  sr={args.samplerate}")
    print("Ctrl+C to stop.")

    with sd.Stream(
        device=(in_idx, out_idx),
        samplerate=args.samplerate,
        blocksize=args.blocksize,
        dtype="float32",
        channels=2,
        latency="low",
        callback=callback,
    ):
        signal.sigwait([signal.SIGINT, signal.SIGTERM])
    print("\nStopped.")


if __name__ == "__main__":
    main()
