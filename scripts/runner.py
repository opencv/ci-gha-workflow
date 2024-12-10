#!/usr/bin/env python3

from subprocess import Popen, PIPE, STDOUT
import argparse
from pathlib import Path
import json
import re
import time

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
        print('\n'.join(summary), flush=True)


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Run gtest executable in GHA context')
    parser.add_argument('exe', help='Executable to run')
    parser.add_argument('--log', type=Path, help='Path to store log')
    parser.add_argument('--timeout', type=int, default=10, help='Timeout in minutes')
    parser.add_argument('--wrap', default='', help="Wrapper command")
    parser.add_argument('--workdir', default='.', help="Change working dir")
    parser.add_argument('--skiplist', type=Path, help="skip-list.json file")
    parser.add_argument('--skipgroup', help="group in skip-list file")
    parser.add_argument('--verbose', help="Output all executable lines, print only errors and summary lines otherwise")

    args, other = parser.parse_known_args()

    status = 0

    print("::group::Run {}".format(args.exe), flush=True)

    options = []

    logfd = None
    if args.log:
        print("Log file: {}".format(args.log))
        try:
            logfd = open(args.log, 'wb')
        except Exception as err:
            print("::error::{}".format(err), flush=True)
            status = -3

    if args.skiplist and args.skipgroup:
        print("Skip list: {}@{}".format(args.skiplist, args.skipgroup))
        try:
            with open(args.skiplist) as f:
                skip = json.load(f)[args.skipgroup]
            for k, v in skip.keys():
                if args.exe.contains(k):
                    options += [ '--gtest_filter=*:-{}'.format(':'.join(v)) ]
                    break
        except Exception as err:
            print("::error::{}".format(err), flush=True)
            status = -2

    if status == 0:
        full_exe = args.wrap.split() + [args.exe] + options + other
        print("Run: {}".format(full_exe), flush=True)
        try:
            proc = Popen(full_exe, stdout=PIPE, stderr=STDOUT, cwd=args.workdir)
            read_process(proc, args.timeout, args.verbose, logfd)
            proc.wait()                    
            status = proc.returncode
        except Exception as err:
            print("::error::{}".format(err), flush=True)
            status = -1

    if logfd:
        logfd.close()

    print("", flush=True)
    print("::notice::Exit status: {}".format(status), flush=True)
    print("::endgroup::", flush=True)

    exit(status)
    