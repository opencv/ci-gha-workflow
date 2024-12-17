#!/usr/bin/env python3

from subprocess import Popen, PIPE, STDOUT
import argparse
from pathlib import Path
import json
import re
import time
import traceback

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


def run_one(wrap, exe, extra, bindir, prefix, logdir, workdir, timeout, verbose=False):

    print("::group::Run {}".format(exe), flush=True)

    status = 0
    logfd = None
    try:
        # Open log file for stdout/stderr
        full_log = workdir / logdir / (prefix + Path(exe).stem + ".txt")
        print("Log: {}".format(full_log), flush=True)
        logfd = open(full_log , 'wb')
        # Build command line
        full_exe = wrap + [bindir / Path(exe)] + extra
        print("Run: {}".format(full_exe), flush=True)
        # Run process and process its output
        proc = Popen(full_exe, stdout=PIPE, stderr=STDOUT, cwd=workdir)
        read_process(proc, timeout, verbose, logfd)
        proc.wait()                    
        status = proc.returncode
    except Exception as err:
        print("::error::{} {}".format(exe, err), flush=True)
        traceback.print_exception(err)
        status = -1
    finally:
        if logfd:
            logfd.close()

    print("", flush=True)
    print("::endgroup::", flush=True)

    if status != 0:
        print("::error::Failure => {} ({})".format(exe, status))
        return False
    else:
        print("::notice::Success => {}".format(exe))
        return True


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Run gtest executable in GHA context')

    parser.add_argument('--plan', type=Path, required=True, help='Path to test plan file (JSON)')
    parser.add_argument('--suite', required=True, help='Suite in test plan (set of executables)')
    parser.add_argument('--filter', help='Filter in test plan (skip some testcases)')
    parser.add_argument('--options', default="default", help='Options in test plan (extra run options)')

    parser.add_argument('--timeout', type=int, default=10, help='Timeout in minutes')
    parser.add_argument('--prefix', default="out_", help='Prefix to add to logs')
    parser.add_argument('--workdir', default='.', type=Path, help="Working directory")
    parser.add_argument('--logdir', type=Path, default='.', help='Directory to store logs (relative to workdir)')
    parser.add_argument('--bindir', default='bin', type=Path, help="Directory with binaries (relative to workdir)")
    parser.add_argument('--verbose', help="Output all executable lines, print only errors and summary lines otherwise")

    args, other = parser.parse_known_args()

    status = True

    with open(args.plan) as f:
        plan = json.load(f)
    suite = plan["suites"][args.suite]

    for exe in suite:
        wrap = []
        extra = []
        if args.options:
            opt_node = plan["options"][args.options]
            if opt_node["wrap"]:
                for k, v in opt_node["wrap"].items():
                    if k in exe:
                        wrap = v.split()
                        break # Note: only one wrapper
            if opt_node["args"]:
                for k, v in opt_node["args"].items():
                    if k in exe:
                        extra.extend(v.split())
        filter = []
        if args.filter:
            for k, v in plan["filters"][args.filter].items():
                if k in exe:
                    filter.extend(v)
        if filter:
            extra.append('--gtest_filter=*:-{}'.format(':'.join(filter)))
                    
        status &= run_one(wrap, exe, extra, args.bindir, args.prefix, args.logdir, args.workdir, args.timeout, args.verbose)

    if status:
        print("::notice::Testing succeeded ({})".format(args.plan))
    else:
        print("::error::Testing failed ({})".format(args.plan))
        exit(1)
    