#!/usr/bin/env python3

import subprocess
import argparse
from pathlib import Path

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Run gtest executable in GHA context')
    parser.add_argument('exe', help='Executable to run')
    parser.add_argument('--log', type=Path, help='Path to store XML log')
    parser.add_argument('--timeout', type=int, default=10, help='Timeout in minutes')
    parser.add_argument('--wrap', default='', help="Wrapper command")
    parser.add_argument('--workdir', default='.', help="Change working dir")

    args, other = parser.parse_known_args()

    print("::group::Run {}".format(args.exe), flush=True)

    options = []
    if args.log:
        options.append('--gtest_output=xml:{}'.format(args.log))
    full_exe = args.wrap.split() + [args.exe] + options + other
    print("Run: {}".format(full_exe), flush=True)
    try:
        res = subprocess.run(full_exe, timeout=args.timeout * 60, check=True, cwd=args.workdir)
        status = res.returncode
    except Exception as err:
        print("", flush=True)
        print("::error::{}".format(err), flush=True)
        status = -1

    print("", flush=True)
    print("Exit status: {}".format(status), flush=True)
    print("::endgroup::", flush=True)

    exit(status)
    