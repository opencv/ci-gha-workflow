#!/usr/bin/env python3

"""Run OpenCV test executables described by a JSON test plan."""

import argparse
import asyncio
from asyncio.subprocess import PIPE, STDOUT
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import traceback


STATE_START = 1
STATE_CASE = 2
STATE_SUM = 3

case_begin = re.compile(r"^\[ RUN      \] (.*)$")
case_end = re.compile(r"^\[       OK \] (.*) \(\d+ ms\)$")
case_fail = re.compile(r"^\[  FAILED  \] (.*) \(\d+ ms\)$")
asan_fail = re.compile(r"^==\d+==ABORTING$")
summary_begin = re.compile(r"^\[----------\] Global test environment tear-down$")


async def read_process(proc, verbose, logfd):
    state = STATE_START
    case_output = []
    summary_output = []

    while True:
        line = await proc.stdout.readline()
        if not line:
            break

        if logfd:
            logfd.write(line)
            logfd.flush()

        line = line.decode("utf-8", errors="replace").rstrip()

        if verbose:
            print(line, flush=True)

        if state == STATE_START:
            if case_begin.match(line):
                state = STATE_CASE
                case_output = [line]
                continue
            if summary_begin.match(line):
                state = STATE_SUM
                summary_output = [line]
                continue
        elif state == STATE_CASE:
            case_output.append(line)
            if case_end.match(line):
                state = STATE_START
                continue
            if case_fail.match(line) or asan_fail.match(line):
                state = STATE_START
                if not verbose:
                    print("\n".join(case_output), flush=True)
                continue
        elif state == STATE_SUM:
            summary_output.append(line)

    if not verbose and summary_output:
        print("\n".join(summary_output), flush=True)


def safe_signal_string(code):
    if code < 0 and abs(code) in signal.valid_signals():
        return "{} ({})".format(code, signal.strsignal(abs(code)))
    return str(code)


async def stop_process(proc):
    if proc is None or proc.returncode is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        proc.kill()
    await proc.wait()


def process_group_options():
    if os.name == "posix":
        return {"start_new_session": True}
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {}


async def run_one(spec, args):
    name = spec["name"]
    grouped = args.jobs == 1
    if grouped:
        print("::group::Run {}".format(name), flush=True)
    else:
        print("::notice title=Test started::{}".format(name), flush=True)
    print("Run {}: {}".format(name, spec["cmd"]), flush=True)
    print("Env {}: {}".format(name, spec["env"]), flush=True)
    print("Log {}: {}".format(name, spec["logname"]), flush=True)

    status = -1
    proc = None
    logfd = None
    started = time.monotonic()
    try:
        full_env = dict(os.environ)
        full_env.update(spec["env"])
        spec["logname"].parent.mkdir(parents=True, exist_ok=True)
        logfd = open(spec["logname"], "wb")
        proc = await asyncio.create_subprocess_exec(
            *spec["cmd"],
            stdout=PIPE,
            stderr=STDOUT,
            cwd=args.workdir,
            env=full_env,
            **process_group_options(),
        )
        print("PID {}: {}".format(name, proc.pid), flush=True)
        await asyncio.wait_for(
            read_process(proc, args.verbose, logfd),
            timeout=args.timeout * 60,
        )
        await proc.wait()
        status = proc.returncode
        print("Return {}: {}".format(name, safe_signal_string(status)), flush=True)
    except asyncio.TimeoutError:
        await stop_process(proc)
        status = proc.returncode if proc else -1
        print(
            "Timeout {} min: {} ({})".format(
                args.timeout, name, safe_signal_string(status)
            ),
            flush=True,
        )
    except asyncio.CancelledError:
        await stop_process(proc)
        raise
    except Exception as err:
        await stop_process(proc)
        print("Exception in {}: {}".format(name, err), flush=True)
        traceback.print_exc(file=sys.stdout)
    finally:
        if logfd:
            logfd.close()
        if grouped:
            print("::endgroup::", flush=True)

    duration = time.monotonic() - started
    if status != 0:
        print("::error title=Test failed::{} ({:.1f}s)".format(name, duration))
        return False, duration

    print("Success => {} ({:.1f}s)".format(name, duration))
    return True, duration


def find_matching_values(mapping, name):
    return [value for pattern, value in mapping.items() if pattern in name]


def make_spec(name, plan, args, index):
    wrap = []
    actual_exe = name
    extra_args = []
    env = {}
    serial = False
    estimated_duration = 0

    if args.options:
        opt_node = plan["options"][args.options]
        wrappers = find_matching_values(opt_node.get("wrap", {}), name)
        if wrappers:
            wrap = wrappers[0].split()
        for value in find_matching_values(opt_node.get("args", {}), name):
            extra_args.extend(value.split())
        executables = find_matching_values(opt_node.get("exe", {}), name)
        if executables:
            actual_exe = executables[0]
        for value in find_matching_values(opt_node.get("env", {}), name):
            env.update(value)
        serial = any(pattern in name for pattern in opt_node.get("serial", []))
        estimates = find_matching_values(
            opt_node.get("estimated_duration_seconds", {}), name
        )
        if estimates:
            estimated_duration = estimates[0]

    filters = []
    if args.filter:
        for one_filter in args.filter:
            for pattern, value in plan["filters"][one_filter].items():
                if pattern in name:
                    filters.extend(value)
    if filters:
        extra_args.append("--gtest_filter=*:-{}".format(":".join(filters)))

    actual_exe = args.workdir / args.bindir / Path(actual_exe)
    if args.exesuffix:
        actual_exe = actual_exe.with_suffix(args.exesuffix)
    error = None
    if not wrap and (not actual_exe.exists() or not actual_exe.is_file()):
        error = "Executable not found: {}".format(actual_exe)

    return {
        "index": index,
        "name": name,
        "cmd": wrap + [actual_exe] + extra_args,
        "env": env,
        "logname": args.logdir / (args.prefix + name + ".txt"),
        "serial": serial,
        "estimated_duration": estimated_duration,
        "error": error,
    }


async def run_phase(specs, worker_count, args, results, stop_requested):
    next_spec = 0

    async def worker():
        nonlocal next_spec
        while next_spec < len(specs):
            if args.fail_fast and stop_requested.is_set():
                return
            spec = specs[next_spec]
            next_spec += 1
            if spec["error"]:
                print("::error::{}".format(spec["error"]), flush=True)
                result = (False, 0.0)
            else:
                result = await run_one(spec, args)
            results[spec["index"]] = result
            if not result[0]:
                stop_requested.set()

    if specs:
        await asyncio.gather(
            *(worker() for _ in range(min(worker_count, len(specs))))
        )


async def run_suite(specs, args):
    results = [None] * len(specs)
    stop_requested = asyncio.Event()

    if args.jobs == 1:
        await run_phase(specs, 1, args, results, stop_requested)
        return results

    parallel = sorted(
        (spec for spec in specs if not spec["serial"]),
        key=lambda spec: (-spec["estimated_duration"], spec["index"]),
    )
    serial = [spec for spec in specs if spec["serial"]]
    await run_phase(parallel, args.jobs, args, results, stop_requested)
    if not (args.fail_fast and stop_requested.is_set()):
        await run_phase(serial, 1, args, results, stop_requested)
    return results


def write_summary(summary_path, specs, results):
    if not summary_path:
        return
    with open(summary_path, "ab") as summary:
        for spec, result in zip(specs, results):
            if result is None:
                line = "- :black_circle: {} => SKIPPED (fail-fast)\n"
                values = (spec["name"],)
            elif result[0]:
                line = "- :white_check_mark: {} => PASS ({:.1f}s)\n"
                values = (spec["name"], result[1])
            else:
                line = "- :x: {} => FAIL ({:.1f}s)\n"
                values = (spec["name"], result[1])
            summary.write(line.format(*values).encode("utf-8"))


def positive_int(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def parse_args():
    parser = argparse.ArgumentParser(description="Run gtest executables in GHA")
    parser.add_argument("--plan", type=Path, required=True, help="Test plan JSON")
    parser.add_argument("--suite", action="append", required=True, help="Suite name")
    parser.add_argument("--filter", action="append", help="Test filter name")
    parser.add_argument("--options", default="default", help="Plan option name")
    parser.add_argument("--timeout", type=int, default=10, help="Per-test timeout (min)")
    parser.add_argument("--prefix", default="out_", help="Log filename prefix")
    parser.add_argument("--workdir", default=".", type=Path, help="Working directory")
    parser.add_argument("--logdir", default=".", type=Path, help="Log directory")
    parser.add_argument("--bindir", default="bin", type=Path, help="Binary directory")
    parser.add_argument("--verbose", action="store_true", help="Output every line")
    parser.add_argument("--summary", type=Path, help="Summary output file")
    parser.add_argument("--exesuffix", help="Executable suffix, e.g. '.exe'")
    parser.add_argument("--jobs", type=positive_int, default=1, help="Parallel tests")
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop scheduling new tests after the first failure",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.logdir.is_absolute():
        args.logdir = args.workdir / args.logdir

    with open(args.plan) as plan_file:
        plan = json.load(plan_file)

    suite = []
    for one_suite in args.suite:
        suite.extend(plan["suites"][one_suite])
    specs = [make_spec(name, plan, args, index) for index, name in enumerate(suite)]

    print(
        "::notice title=Test schedule::{} executables, {} workers".format(
            len(specs), args.jobs
        ),
        flush=True,
    )
    results = asyncio.run(run_suite(specs, args))
    write_summary(args.summary, specs, results)

    passed = sum(result is not None and result[0] for result in results)
    if passed == len(specs):
        print(
            "::notice::Testing PASS (plan: {}, count: {}, jobs: {})".format(
                args.plan, len(specs), args.jobs
            )
        )
        return 0

    failed = sum(result is not None and not result[0] for result in results)
    skipped = sum(result is None for result in results)
    print(
        "::error::Testing FAIL (plan: {}, failed: {}, skipped: {})".format(
            args.plan, failed, skipped
        )
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
