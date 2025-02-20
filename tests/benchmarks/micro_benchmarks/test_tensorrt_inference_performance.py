# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Tests for tensorrt-inference benchmark."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.helper import decorator
from superbench.benchmarks import BenchmarkRegistry, BenchmarkType, ReturnCode, Platform
from superbench.benchmarks.result import BenchmarkResult


class TensorRTInferenceBenchmarkTestCase(unittest.TestCase):
    """Class for tensorrt-inferencee benchmark test cases."""
    def setUp(self):
        """Hook method for setting up the test fixture before exercising it."""
        self.benchmark_name = 'tensorrt-inference'
        self.__tmp_dir = tempfile.mkdtemp()
        self.__curr_micro_path = os.environ.get('SB_MICRO_PATH', '')
        os.environ['SB_MICRO_PATH'] = self.__tmp_dir
        os.environ['TORCH_HOME'] = self.__tmp_dir
        (Path(self.__tmp_dir) / 'bin').mkdir(parents=True, exist_ok=True)
        (Path(self.__tmp_dir) / 'bin' / 'trtexec').touch(mode=0o755, exist_ok=True)

    def tearDown(self):
        """Hook method for deconstructing the test fixture after testing it."""
        shutil.rmtree(self.__tmp_dir)
        os.environ['SB_MICRO_PATH'] = self.__curr_micro_path
        del os.environ['TORCH_HOME']

    def test_tensorrt_inference_cls(self):
        """Test tensorrt-inference benchmark class."""
        for platform in Platform:
            (benchmark_cls, _) = BenchmarkRegistry._BenchmarkRegistry__select_benchmark(self.benchmark_name, platform)
            if platform is Platform.CUDA:
                self.assertIsNotNone(benchmark_cls)
            else:
                self.assertIsNone(benchmark_cls)

    @decorator.cuda_test
    @decorator.pytorch_test
    def test_tensorrt_inference_params(self):
        """Test tensorrt-inference benchmark preprocess with different parameters."""
        (benchmark_cls, _) = BenchmarkRegistry._BenchmarkRegistry__select_benchmark(self.benchmark_name, Platform.CUDA)

        test_cases = [
            {
                'precision': 'fp32',
            },
            {
                'pytorch_models': ['resnet50', 'mnasnet0_5'],
                'precision': 'fp16',
            },
            {
                'pytorch_models': ['resnet50'],
                'batch_size': 4,
            },
            {
                'batch_size': 4,
                'iterations': 128,
            },
        ]
        for test_case in test_cases:
            with self.subTest(msg='Testing with case', test_case=test_case):
                parameter_list = []
                if 'pytorch_models' in test_case:
                    parameter_list.append(f'--pytorch_models {" ".join(test_case["pytorch_models"])}')
                if 'precision' in test_case:
                    parameter_list.append(f'--precision {test_case["precision"]}')
                if 'batch_size' in test_case:
                    parameter_list.append(f'--batch_size {test_case["batch_size"]}')
                if 'iterations' in test_case:
                    parameter_list.append(f'--iterations {test_case["iterations"]}')

                # Check basic information
                benchmark = benchmark_cls(self.benchmark_name, parameters=' '.join(parameter_list))
                self.assertTrue(benchmark)

                # Limit model number
                benchmark._pytorch_models = benchmark._pytorch_models[:1]
                benchmark._TensorRTInferenceBenchmark__model_cache_path = Path(self.__tmp_dir) / 'hub/checkpoints'

                # Preprocess
                ret = benchmark._preprocess()
                self.assertTrue(ret)
                self.assertEqual(ReturnCode.SUCCESS, benchmark.return_code)
                self.assertEqual(BenchmarkType.MICRO, benchmark.type)
                self.assertEqual(self.benchmark_name, benchmark.name)

                # Check parameters
                self.assertEqual(
                    test_case.get('pytorch_models', benchmark._pytorch_models),
                    benchmark._args.pytorch_models,
                )
                self.assertEqual(
                    test_case.get('precision', 'int8'),
                    benchmark._args.precision,
                )
                self.assertEqual(
                    test_case.get('batch_size', 32),
                    benchmark._args.batch_size,
                )
                self.assertEqual(
                    test_case.get('iterations', 256),
                    benchmark._args.iterations,
                )

                # Check models
                for model in benchmark._args.pytorch_models:
                    self.assertTrue(
                        (benchmark._TensorRTInferenceBenchmark__model_cache_path / f'{model}.onnx').is_file()
                    )

                # Command list should equal to default model number
                self.assertEqual(
                    len(test_case.get('pytorch_models', benchmark._pytorch_models)), len(benchmark._commands)
                )

    @decorator.load_data('tests/data/tensorrt_inference.log')
    def test_tensorrt_inference_result_parsing(self, test_raw_log):
        """Test tensorrt-inference benchmark result parsing."""
        (benchmark_cls, _) = BenchmarkRegistry._BenchmarkRegistry__select_benchmark(self.benchmark_name, Platform.CUDA)
        benchmark = benchmark_cls(self.benchmark_name, parameters='')
        benchmark._args = SimpleNamespace(pytorch_models=['model_0', 'model_1'])
        benchmark._result = BenchmarkResult(self.benchmark_name, BenchmarkType.MICRO, ReturnCode.SUCCESS, run_count=1)

        # Positive case - valid raw output
        self.assertTrue(benchmark._process_raw_result(0, test_raw_log))
        self.assertEqual(ReturnCode.SUCCESS, benchmark.return_code)

        self.assertEqual(6, len(benchmark.result))
        for tag in ['mean', '99']:
            self.assertEqual(0.5, benchmark.result[f'gpu_lat_ms_{tag}'][0])
            self.assertEqual(0.6, benchmark.result[f'host_lat_ms_{tag}'][0])
            self.assertEqual(1.0, benchmark.result[f'end_to_end_lat_ms_{tag}'][0])

        # Negative case - invalid raw output
        self.assertFalse(benchmark._process_raw_result(1, 'Invalid raw output'))
