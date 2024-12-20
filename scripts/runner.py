#!/usr/bin/env python3

from subprocess import Popen, PIPE, STDOUT
import argparse
from pathlib import Path
import json
import re
import time
import traceback
import os
import sys

STATE_START = 1
STATE_CASE = 2
STATE_SUM = 3

case_begin = re.compile(r"^\[ RUN      \] (.*)$")
case_end = re.compile(r"^\[       OK \] (.*) \(\d+ ms\)$")
case_fail = re.compile(r"^\[  FAILED  \] (.*) \(\d+ ms\)$")
summary_begin = re.compile(r"^\[----------\] Global test environment tear-down$")

def read_process(proc, timeout, verbose, logfd):
    state = STATE_START
    start = time.time()
    last = start
    case_output = []
    summary_output = []

    for line in proc.stdout:

        if logfd:
            logfd.write(line)
            logfd.flush()

        line = line.decode('utf-8').rstrip()

        if verbose:
            print(line, flush=True)

        elapsed = time.time() - start
        if elapsed > timeout * 60:
            raise TimeoutError("Timeout: {} min, Elapsed: {} sec".format(timeout, elapsed))

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
            if case_fail.match(line):
                state = STATE_START
                if not verbose:
                    print('\n'.join(case_output), flush=True)
                continue
        elif state == STATE_SUM:
            summary_output.append(line)
            continue

    if not verbose:
        print('\n'.join(summary_output), flush=True)


def run_one(name, cmd, logname, env, args):

    print("::group::Run {}".format(name), flush=True)
    print("Run: {}".format(cmd), flush=True)
    print("Env: {}".format(env), flush=True)
    print("Log: {}".format(logname), flush=True)

    status = 0
    logfd = None
    try:
        full_env = dict(os.environ)
        full_env.update(env)
        logfd = open(logname, 'wb')
        proc = Popen(cmd, stdout=PIPE, stderr=STDOUT, cwd=args.workdir, env=full_env)
        print("PID: {}".format(proc.pid), flush=True)
        read_process(proc, args.timeout, args.verbose, logfd)
        proc.wait()
        status = proc.returncode
        print("Return code: {}".format(status), flush=True)
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
        # print("::notice::Success => {}".format(name))
        print("Success => {}".format(name))
        return True


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Run gtest executable in GHA context')

    parser.add_argument('--plan', type=Path, required=True, help='Path to test plan file (JSON)')
    parser.add_argument('--suite', action='append', required=True, help='Suite in test plan (set of executables), multiple allowed')
    parser.add_argument('--filter', action='append', help='Filter in test plan (skip some testcases), multiple allowed')
    parser.add_argument('--options', default="default", help='Options in test plan (extra run options)')

    parser.add_argument('--timeout', type=int, default=10, help='Timeout in minutes')
    parser.add_argument('--prefix', default="out_", help='Prefix to add to logs')
    parser.add_argument('--workdir', default='.', type=Path, help="Working directory")
    parser.add_argument('--logdir', default='.', type=Path, help='Directory to store logs (relative to workdir)')
    parser.add_argument('--bindir', default='bin', type=Path, help="Directory with binaries (relative to workdir)")
    parser.add_argument('--verbose', help="Output all executable lines, print only errors and summary lines otherwise")
    parser.add_argument('--summary', type=Path, help="Path to summary file to generate")

    args, other = parser.parse_known_args()

    status = True

    with open(args.plan) as f:
        plan = json.load(f)

    suite = []
    for one_suite in args.suite:
        suite.extend(plan["suites"][one_suite])

    sumfd = None
    if args.summary:
        sumfd = open(args.summary, 'wb')

    for name in suite:
        wrap = []
        actual_exe = name
        extra_args = []
        env = {}
        if args.options:
            opt_node = plan["options"][args.options]
            # Add wrapper command
            if opt_node["wrap"]:
                for k, v in opt_node["wrap"].items():
                    if k in name:
                        wrap = v.split()
                        break # Note: only one wrapper
            # Add extra test arguments
            if opt_node["args"]:
                for k, v in opt_node["args"].items():
                    if k in name:
                        extra_args.extend(v.split())
            # Use different executable
            if opt_node["exe"]:
                for k, v in opt_node["exe"].items():
                    if k in name:
                        actual_exe = v
                        break # Note: only one exe change
            # Change environment
            if opt_node["env"]:
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
            extra_args.append('--gtest_filter=*:-{}'.format(':'.join(filter)))

        actual_exe = args.workdir / args.bindir / Path(actual_exe)
        if not actual_exe.exists() or not actual_exe.is_file():
            print("::error::Executable not found: {}".format(actual_exe))
            res = False
        else:
            cmd = wrap + [actual_exe] + extra_args
            logname = args.workdir / args.logdir / (args.prefix + name + ".txt")
            res = run_one(name, cmd, logname, env, args)

        if sumfd:
            sum = "- :white_check_mark: {} => PASS\n" if res else "- :x: {} => FAIL\n"
            sumfd.write(sum.format(name).encode("utf-8"))

        status &= res

    if sumfd:
        sumfd.close()

    if status:
        print("::notice::Testing succeeded (plan: {}, count: {})".format(args.plan, len(suite)))
    else:
        print("::error::Testing failed ({})".format(args.plan))
        exit(1)
