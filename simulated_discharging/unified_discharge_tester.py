"""Run a signed-current battery schedule on a DP811A and KEL103.

CSV columns: time_seconds,current_amps. Positive charges, negative discharges.
The last row must be 0 A: its timestamp ends the run.
Software OFF commands are not physical isolation. Use independent battery
protection and confirm both devices tolerate parallel battery connection.
"""

import argparse
from contextlib import ExitStack
import csv
import math
import os
from pathlib import Path
import sys
import time

import pyvisa
from kelctl import KELSerial


def finite_number(text, name):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def positive_number(text):
    try:
        value = finite_number(text, "argument")
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return value


def nonnegative_number(text):
    try:
        value = finite_number(text, "argument")
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if value < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return value


def read_schedule(path, max_charge, max_discharge):
    points = []
    with open(path, newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != ["time_seconds", "current_amps"]:
            raise ValueError("CSV header must be: time_seconds,current_amps")
        for line, row in enumerate(reader, start=2):
            if None in row:
                raise ValueError(f"CSV line {line}: too many columns")
            try:
                t = finite_number(row["time_seconds"], "time_seconds")
                current = finite_number(row["current_amps"], "current_amps")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"CSV line {line}: {exc}") from exc
            if t < 0 or (points and t <= points[-1][0]):
                raise ValueError(f"CSV line {line}: times must strictly increase from 0")
            if current > max_charge or -current > max_discharge:
                raise ValueError(f"CSV line {line}: current exceeds configured limit")
            points.append((t, current))
    if len(points) < 2 or points[0][0] != 0 or points[-1][1] != 0:
        raise ValueError("Schedule needs a row at 0 s and a final 0 A row at a later time")
    return points


def check_voltage(voltage, low, high):
    """Enforce both bounds in every mode, including before charging/discharging."""
    if not math.isfinite(voltage) or voltage <= 0:
        raise RuntimeError(f"Invalid battery voltage reading: {voltage!r}")
    if voltage <= low:
        raise RuntimeError(f"Battery at/below minimum voltage: {voltage:.4f} V")
    if voltage >= high:
        raise RuntimeError(f"Battery at/above maximum voltage: {voltage:.4f} V")


def same_file(a, b):
    a, b = Path(a), Path(b)
    return a.resolve() == b.resolve() or (a.exists() and b.exists() and os.path.samefile(a, b))


def verify_psu_off(psu):
    # Verify this SCPI query/response with your DP811A before running on a battery.
    state = psu.query(":OUTP? CH1").strip().upper()
    if state not in ("OFF", "0"):
        raise RuntimeError(f"PSU output not confirmed OFF: {state!r}")


def stop_outputs(psu, load, tolerance, settle):
    """Command both OFF and verify readback and near-zero branch currents."""
    psu.write(":OUTP CH1,OFF")
    load.input.off()
    load.current = 0.0
    time.sleep(settle)
    verify_psu_off(psu)
    for name, current in (("PSU", float(psu.query(":MEAS:CURR? CH1"))),
                          ("load", float(load.measured_current))):
        if not math.isfinite(current) or abs(current) > tolerance:
            raise RuntimeError(f"{name} current not confirmed near zero: {current!r} A")


def run(args, points):
    rm = psu = load = None
    stack = ExitStack()
    shutdown_failures = []
    try:
        rm = pyvisa.ResourceManager()
        psu = rm.open_resource(args.psu_address)
        psu.timeout = 5000
        psu.write(":OUTP CH1,OFF")  # Before any ID queries.
        load = stack.enter_context(KELSerial(args.load_port))
        load.input.off()  # Before any model queries.
        # Configure and verify the actual KEL serial timeout for your kelctl version.
        stop_outputs(psu, load, args.off_current_tolerance, args.off_settle)
        print("Load:", load.model, "| PSU:", psu.query("*IDN?").strip())

        with open(args.log, "w", newline="") as logfile:
            writer = csv.writer(logfile)
            writer.writerow(["elapsed_seconds", "set_current_amps", "measured_current_amps",
                             "voltage_volts", "power_watts", "mode"])
            start = time.monotonic()
            next_sample = start
            index = 0
            active = None
            print("Running; press Ctrl+C to stop")

            while True:
                elapsed = time.monotonic() - start
                prev_index = index
                while index + 1 < len(points) and elapsed >= points[index + 1][0]:
                    index += 1
                if index - prev_index > 1 or (active is None and index != 0):
                    raise RuntimeError(f"Schedule step(s) skipped at t={elapsed:.3f}s")
                if index == len(points) - 1:
                    break
                requested = points[index][1]
                mode = "charge" if requested > 0 else "discharge" if requested < 0 else "idle"

                if (mode, requested) != active:
                    stop_outputs(psu, load, args.off_current_tolerance, args.off_settle)
                    voltage = float(load.measured_voltage)
                    check_voltage(voltage, args.min_voltage, args.max_voltage)
                    if time.monotonic() - start >= points[index + 1][0]:
                        raise RuntimeError("Schedule step expired during switching; aborting")
                    if mode == "charge":
                        psu.write(f":APPL CH1,{args.charge_voltage},{requested}")
                        if time.monotonic() - start >= points[index + 1][0]:
                            raise RuntimeError("Schedule step expired during PSU setup")
                        psu.write(":OUTP CH1,ON")
                        time.sleep(args.on_settle)  # Output reads ~0 V until it settles.
                    elif mode == "discharge":
                        load.current = -requested
                        if time.monotonic() - start >= points[index + 1][0]:
                            raise RuntimeError("Schedule step expired during load setup")
                        load.input.on()
                    active = (mode, requested)
                    next_sample = time.monotonic()
                    print(f"[{elapsed:8.2f}s] {mode:9s} {requested:+.3f} A")

                if time.monotonic() >= next_sample:
                    if mode == "charge":
                        voltage = float(psu.query(":MEAS:VOLT? CH1"))
                        measured_current = float(psu.query(":MEAS:CURR? CH1"))
                    else:
                        voltage = float(load.measured_voltage)
                        measured_current = -float(load.measured_current) if mode == "discharge" else 0.0
                    check_voltage(voltage, args.min_voltage, args.max_voltage)
                    if not math.isfinite(measured_current):
                        raise RuntimeError("Invalid current measurement")
                    sample_time = time.monotonic() - start
                    writer.writerow([f"{sample_time:.3f}", f"{requested:.4f}",
                                     f"{measured_current:.4f}", f"{voltage:.4f}",
                                     f"{voltage * measured_current:.4f}", mode])
                    logfile.flush()
                    print(f"[{sample_time:8.2f}s] {voltage:.3f} V  {measured_current:+.3f} A")
                    next_sample = time.monotonic() + args.interval

                deadline = min(start + points[index + 1][0], next_sample)
                time.sleep(max(0, deadline - time.monotonic()))
    finally:
        # Try every shutdown action; keep connections open for OFF verification.
        for label, action in (
            ("PSU off", lambda: psu.write(":OUTP CH1,OFF") if psu else None),
            ("Load off", lambda: load.input.off() if load else None),
            ("Load current zero", lambda: setattr(load, "current", 0.0) if load else None),
            ("PSU OFF readback", lambda: verify_psu_off(psu) if psu else None),
            ("Close load", stack.close),
            ("Close PSU", lambda: psu.close() if psu else None),
            ("Close VISA manager", lambda: rm.close() if rm else None),
        ):
            try:
                action()
            except Exception as exc:
                shutdown_failures.append(label)
                print(f"SHUTDOWN WARNING ({label}): {exc}", file=sys.stderr)
        if shutdown_failures and sys.exc_info()[0] is None:
            raise RuntimeError(f"Shutdown failed ({', '.join(shutdown_failures)}); check hardware manually")
    print(f"Finished; log saved to {args.log}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("load_port", help="KEL load serial port")
    parser.add_argument("psu_address", help="DP811A VISA resource address")
    parser.add_argument("schedule", help="CSV with time_seconds,current_amps")
    parser.add_argument("--charge-voltage", type=positive_number, required=True,
                        help="PSU voltage setting (V), below maximum battery voltage")
    parser.add_argument("--min-voltage", type=positive_number, required=True)
    parser.add_argument("--max-voltage", type=positive_number, required=True)
    parser.add_argument("--max-charge", type=positive_number, required=True)
    parser.add_argument("--max-discharge", type=positive_number, required=True)
    parser.add_argument("--interval", type=positive_number, default=1.0,
                        help="measurement interval in seconds (default: 1)")
    parser.add_argument("--off-settle", type=nonnegative_number, default=0.2,
                        help="seconds to wait after OFF commands before readback (default: 0.2)")
    parser.add_argument("--on-settle", type=nonnegative_number, default=1.0,
                        help="seconds to wait after PSU output ON before measuring (default: 1)")
    parser.add_argument("--off-current-tolerance", type=nonnegative_number, required=True,
                        help="allowed absolute OFF-state branch current (A); use instrument accuracy")
    parser.add_argument("--log", default="battery_log.csv", help="output CSV log")
    args = parser.parse_args()
    if not args.min_voltage < args.charge_voltage < args.max_voltage:
        parser.error("require min-voltage < charge-voltage < max-voltage")
    try:
        if same_file(args.schedule, args.log):
            raise ValueError("log file must not refer to the schedule file")
        points = read_schedule(args.schedule, args.max_charge, args.max_discharge)
        run(args, points)
    except KeyboardInterrupt:
        print("Stopped by user; check hardware if shutdown warnings appeared", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, pyvisa.VisaIOError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
