import argparse
import os
import sys


parser = argparse.ArgumentParser(description='Check patch size.')
parser.add_argument('-f','--file_path', help='Path to the bundle file.', default='test.bundle')
args = parser.parse_args()

try:
    patch_size = os.stat(args.file_path).st_size
except IOError:
    print("Bundle file does not exist.")
    sys.exit(0)

def patch_size_convert():
    kilobytes = patch_size / 1024
    megabytes = kilobytes / 1024
    print(("File size: %d bytes = %d KiB = %d MiB") % (patch_size, kilobytes, megabytes))

def check_patch_limits():
    if patch_size > 1024000:
        print('Patch size default limit exceeded: 1024 KiB')
        sys.exit(1)


if __name__ == '__main__':
    patch_size_convert()
    check_patch_limits()
