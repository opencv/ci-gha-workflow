#!/usr/bin/env python3

import subprocess
import argparse
from pathlib import Path

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Run gtest executable in GHA context')
    parser.add_argument('exe', help='Executable to run')
    parser.add_argument('--log', type=Path, help='Path to store XML log')
    parser.add_argument('--timeout', type=int, default=60, help='Timeout in minutes')

    args, other = parser.parse_known_args()

    print("::group::Run {}".format(args.exe))

    options = []
    if args.log:
        options.append('--gtest_output=xml:{}'.format(args.log))
    full_exe = [args.exe] + options + other
    print("Run: {}".format(full_exe))
    try:
        res = subprocess.run(full_exe, timeout=args.timeout, check=True)
        status = res.returncode
    except Exception as err:
        print("::error::{}".format(err))
        status = -1

    print("Exit status: {}".format(status))
    print("::endgroup::")

    exit(status)
    