#!/usr/bin/env python

from argparse import ArgumentParser
from subprocess import check_call
import os

def do_the_job(src, dst):
    ''' Helper '''
    def pack(files, res, cwd):
        if len(files) < 1:
            print("No items to pack in %s" % cwd)
            return
        print("")
        print("====== Pack %d items in %s to %s" % (len(files), cwd, res))
        print("")
        check_call(["zip", "-r", "-9", "-y", os.path.join(dst, res)] + files, cwd=cwd)

    doxy_path = os.path.join(src, "doxygen", "html")
    if os.path.isdir(doxy_path):
        pack(os.listdir(doxy_path), "doc_doxygen.zip", doxy_path)

    pdfs = [f for f in os.listdir(src) if f.endswith(".pdf")]
    if len(pdfs) > 0:
        pack(pdfs, "doc_sphinx.zip", src)

if __name__ == '__main__':
    parser = ArgumentParser(description="Pack OpenCV documentation (2.4.x and 3.x)")
    parser.add_argument("docs", help="path to build/docs dir")
    parser.add_argument("dst", help="folder to store result zip files")
    args = parser.parse_args()
    if not os.path.isdir(args.docs):
        raise StandardError("Source folder (%s) does not exist" % args.docs)
    if not os.path.isdir(args.dst):
        os.makedirs(args.dst)
    do_the_job(os.path.abspath(args.docs), os.path.abspath(args.dst))
