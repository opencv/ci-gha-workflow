#!/usr/bin/env python3

"""
This script runs Google Test executables specified in a test plan file (JSON).
- Supports multiple suites, filters for specific tests, and optional wrappers or environment changes.
- Logs output to files and summarizes results, handling timeouts and errors.
- Outputs GitHub Actions formatted log messages and workflow summaries.
"""

import argparse
from pathlib import Path
import json
import re
import traceback
import os
import sys
import asyncio
import signal
from asyncio.subprocess import PIPE, STDOUT


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

        line = line.decode("utf-8").rstrip()

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
            continue

    if not verbose:
        print("\n".join(summary_output), flush=True)

def safe_signal_string(code):
    if code < 0 and abs(code) in signal.valid_signals():
        return "{} ({})".format(code, signal.strsignal(abs(code)))
    else:
        return str(code)

async def run_one(name, cmd, logname, env, args):
    print("::group::Run {}".format(name), flush=True)
    print("Run: {}".format(cmd), flush=True)
    print("Env: {}".format(env), flush=True)
    print("Log: {}".format(logname), flush=True)

    status = 0
    logfd = None
    try:
        full_env = dict(os.environ)
        full_env.update(env)
        logfd = open(logname, "wb")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=PIPE,
            stderr=STDOUT,
            cwd=args.workdir,
            env=full_env
        )
        print("PID: {}".format(proc.pid), flush=True)
        await asyncio.wait_for(read_process(proc, args.verbose, logfd), timeout=args.timeout * 60)
        await proc.wait()
        status = proc.returncode
        print("Return: {}".format(safe_signal_string(status)), flush=True)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        status = proc.returncode
        print("Timeout {} min: {}".format(args.timeout, safe_signal_string(status)), flush=True)
    except Exception as err:
        print("Exception: {}".format(err), flush=True)
        traceback.print_exc(file=sys.stdout)
        status = -1
    finally:
        if logfd:
            logfd.close()

    print("::endgroup::", flush=True)

    if status != 0:
        print("::error::Failure => {} ({})".format(name, status))
        return False
    else:
        print("Success => {}".format(name))
        return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run gtest executable in GHA context")
    parser.add_argument("--plan", type=Path, required=True, help="Path to test plan file (JSON)")
    parser.add_argument("--suite", action="append", required=True, help="Suite in test plan (set of executables), multiple allowed")
    parser.add_argument("--filter", action="append", help="Filter in test plan (skip some testcases), multiple allowed")
    parser.add_argument("--options", default="default", help="Options in test plan (extra run options)")
    parser.add_argument("--timeout", type=int, default=10, help="Timeout in minutes")
    parser.add_argument("--prefix", default="out_", help="Prefix to add to logs")
    parser.add_argument("--workdir", default=".", type=Path, help="Working directory")
    parser.add_argument("--logdir", default=".", type=Path, help="Directory to store logs (either absolute or relative to workdir)")
    parser.add_argument("--bindir", default="bin", type=Path, help="Directory with binaries (relative to workdir)")
    parser.add_argument("--verbose", action='store_true', help="Output all lines")
    parser.add_argument("--summary", type=Path, help="Path to summary file to generate")
    parser.add_argument("--exesuffix", type=str, help="Suffix for executables (e.g. '.exe' or 'd.exe')")
    args = parser.parse_args()

    if not args.logdir.is_absolute():
        args.logdir = args.workdir / args.logdir

    status = True

    with open(args.plan) as f:
        plan = json.load(f)

    suite = []
    for one_suite in args.suite:
        suite.extend(plan["suites"][one_suite])

    sumfd = None
    if args.summary:
        sumfd = open(args.summary, "wb")

    for name in suite:
        wrap = []
        actual_exe = name
        extra_args = []
        env = {}
        if args.options:
            opt_node = plan["options"][args.options]
            # Add wrapper command
            if opt_node.get("wrap"):
                for k, v in opt_node["wrap"].items():
                    if k in name:
                        wrap = v.split()
                        break  # Note: only one wrapper
            # Add extra test arguments
            if opt_node.get("args"):
                for k, v in opt_node["args"].items():
                    if k in name:
                        extra_args.extend(v.split())
            # Use different executable
            if opt_node.get("exe"):
                for k, v in opt_node["exe"].items():
                    if k in name:
                        actual_exe = v
                        break  # Note: only one exe change
            # Change environment
            if opt_node.get("env"):
                for k, v in opt_node["env"].items():
                    if k in name:
                        env.update(v)

        filter = []
        if args.filter:
            for one_filter in args.filter:
                for k, v in plan["filters"][one_filter].items():
                    if k in name:
                        filter.extend(v)
        if filter:
            extra_args.append("--gtest_filter=*:-{}".format(":".join(filter)))

        actual_exe = args.workdir / args.bindir / Path(actual_exe)
        if args.exesuffix:
            actual_exe = actual_exe.with_suffix(args.exesuffix)
        if len(wrap) == 0 and (not actual_exe.exists() or not actual_exe.is_file()):
            print("Executable not found: {}".format(actual_exe))
            res = -3
        else:
            cmd = wrap + [actual_exe] + extra_args
            logname = args.workdir / args.logdir / (args.prefix + name + ".txt")
            res = asyncio.run(run_one(name, cmd, logname, env, args))

        if sumfd:
            sum = "- :white_check_mark: {} => PASS\n" if res else "- :x: {} => FAIL\n"
            sumfd.write(sum.format(name).encode("utf-8"))

        status &= res

    if sumfd:
        sumfd.close()

    if status:
        print("::notice::Testing PASS (plan: {}, count: {})".format(args.plan, len(suite)))
    else:
        print("::error::Testing FAIL (plan: {})".format(args.plan))
        exit(1)
