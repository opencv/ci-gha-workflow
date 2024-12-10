#!/usr/bin/env python3

import subprocess
import argparse
from pathlib import Path
import json

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Run gtest executable in GHA context')
    parser.add_argument('exe', help='Executable to run')
    parser.add_argument('--log', type=Path, help='Path to store XML log')
    parser.add_argument('--timeout', type=int, default=10, help='Timeout in minutes')
    parser.add_argument('--wrap', default='', help="Wrapper command")
    parser.add_argument('--workdir', default='.', help="Change working dir")
    parser.add_argument('--skiplist', type=Path, help="skip-list.json file")
    parser.add_argument('--skipgroup', help="group in skip-list file")

    args, other = parser.parse_known_args()

    print("::group::Run {}".format(args.exe), flush=True)

    options = []

    if args.log:
        options.append('--gtest_output=xml:{}'.format(args.log))

    if args.skiplist and args.skipgroup:
        try:
            with open(args.skiplist) as f:
                skip = json.load(f)[args.skipgroup]
            for k, v in skip.keys():
                if args.exe.contains(k):
                    options += [ '--gtest_filter=*:-{}'.format(':'.join(v))]
                    break
        except Exception as err:
            print("::error::{}".format(err), flush=True)
            status = -2

    if status == 0:
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
    print("::notice::Exit status: {}".format(status), flush=True)
    print("::endgroup::", flush=True)

    exit(status)
    