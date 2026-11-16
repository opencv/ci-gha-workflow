#!/usr/bin/env python3

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock


RUNNER_PATH = Path(__file__).with_name("runner.py")
SPEC = importlib.util.spec_from_file_location("ci_runner", RUNNER_PATH)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_spec(index, name, serial=False, estimated_duration=0):
    return {
        "index": index,
        "name": name,
        "cmd": [],
        "env": {},
        "logname": Path("unused"),
        "serial": serial,
        "estimated_duration": estimated_duration,
        "error": None,
    }


class SchedulerTest(unittest.TestCase):
    def test_parallel_workers_start_longest_estimated_tests_first(self):
        specs = [
            test_spec(0, "short", estimated_duration=10),
            test_spec(1, "longest", estimated_duration=100),
            test_spec(2, "medium", estimated_duration=50),
        ]
        args = SimpleNamespace(jobs=2, fail_fast=False)
        started = []

        async def fake_run_one(spec, unused_args):
            started.append(spec["name"])
            return True, 0.01

        with mock.patch.object(runner, "run_one", side_effect=fake_run_one):
            results = asyncio.run(runner.run_suite(specs, args))

        self.assertEqual(started, ["longest", "medium", "short"])
        self.assertTrue(all(result[0] for result in results))

    def test_parallel_workers_respect_limit_and_serial_phase(self):
        specs = [
            test_spec(0, "first"),
            test_spec(1, "second"),
            test_spec(2, "third"),
            test_spec(3, "serial", serial=True),
        ]
        args = SimpleNamespace(jobs=2, fail_fast=False)
        active = 0
        peak = 0
        parallel_finished = 0

        async def fake_run_one(spec, unused_args):
            nonlocal active, peak, parallel_finished
            if spec["serial"]:
                self.assertEqual(active, 0)
                self.assertEqual(parallel_finished, 3)
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            if not spec["serial"]:
                parallel_finished += 1
            return True, 0.01

        with mock.patch.object(runner, "run_one", side_effect=fake_run_one):
            results = asyncio.run(runner.run_suite(specs, args))

        self.assertEqual(peak, 2)
        self.assertTrue(all(result[0] for result in results))

    def test_fail_fast_stops_scheduling_new_tests(self):
        specs = [test_spec(index, str(index)) for index in range(3)]
        args = SimpleNamespace(jobs=1, fail_fast=True)
        called = []

        async def fake_run_one(spec, unused_args):
            called.append(spec["name"])
            return False, 0.01

        with mock.patch.object(runner, "run_one", side_effect=fake_run_one):
            results = asyncio.run(runner.run_suite(specs, args))

        self.assertEqual(called, ["0"])
        self.assertEqual(results, [(False, 0.01), None, None])

    def test_missing_executable_is_a_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(
                options="default",
                filter=None,
                workdir=root,
                bindir=Path("bin"),
                exesuffix=None,
                logdir=root,
                prefix="out_",
            )
            plan = {
                "options": {"default": {}},
                "filters": {},
            }
            spec = runner.make_spec("does_not_exist", plan, args, 0)

        self.assertIn("Executable not found", spec["error"])

    def test_duration_estimate_is_read_from_selected_options(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "bin" / "opencv_test_core"
            executable.parent.mkdir()
            executable.touch()
            args = SimpleNamespace(
                options="arm-debug",
                filter=None,
                workdir=root,
                bindir=Path("bin"),
                exesuffix=None,
                logdir=root,
                prefix="out_",
            )
            plan = {
                "options": {
                    "arm-debug": {
                        "estimated_duration_seconds": {
                            "opencv_test_core": 1440
                        }
                    }
                },
                "filters": {},
            }
            spec = runner.make_spec("opencv_test_core", plan, args, 0)

        self.assertEqual(spec["estimated_duration"], 1440)

    def test_summary_preserves_plan_order_and_durations(self):
        specs = [test_spec(0, "pass"), test_spec(1, "fail"), test_spec(2, "skip")]
        results = [(True, 1.25), (False, 2.5), None]
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            runner.write_summary(summary, specs, results)
            text = summary.read_text()

        self.assertIn("pass => PASS (1.2s)", text)
        self.assertIn("fail => FAIL (2.5s)", text)
        self.assertIn("skip => SKIPPED (fail-fast)", text)
        self.assertLess(text.index("pass"), text.index("fail"))
        self.assertLess(text.index("fail"), text.index("skip"))


if __name__ == "__main__":
    unittest.main()
