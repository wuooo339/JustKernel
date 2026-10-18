"""CPU reference regression tests; no CANN execution or official score claims."""

import importlib.util
import sys
import unittest
from pathlib import Path


# ---- ReferenceTests ---------------------------------------------------------
@unittest.skipIf(
    sys.platform != "linux" or importlib.util.find_spec("torch") is None,
    "Optional Linux CPU simulator dependencies",
)
class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "src/aworker/lab/resources/simulator/worker.py"
        spec = importlib.util.spec_from_file_location("reference_worker", path)
        cls.worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.worker)

    # ---- widening before multiplication avoids half intermediate rounding ---
    def test_half_multiplication_is_widened_before_reduction(self):
        import numpy as np

        b = np.array([[1 + 2**-10, 1 + 2**-10]], dtype=np.float16)
        c = np.array([[1 + 2**-10, -1]], dtype=np.float16)
        out = self.worker.reference_outputs([np.ones_like(b), b, c], (1,), False)
        expected = np.float16(2**-10 + 2**-20)
        self.assertEqual(out[1][0], expected)
        self.assertNotEqual(out[1][0], (b * c).sum(dtype=np.float32).astype(np.float16))

    # ---- guard the statement's reduction implementation on realistic inputs --
    def test_large_fp32_reference_matches_pytorch_not_a_numpy_replacement(self):
        import numpy as np
        import torch

        rng = np.random.default_rng(8)
        b, c = [rng.uniform(-1, 1, size=(1024, 1024)).astype(np.float32) for _ in range(2)]
        output = self.worker.reference_outputs([np.ones_like(b), b, c], (0, 1), False)[1]
        expected = (torch.from_numpy(b).float() * torch.from_numpy(c).float()).sum().numpy()
        np.testing.assert_array_equal(output, expected)
        self.assertEqual(torch.get_num_threads(), 1)


if __name__ == "__main__":
    unittest.main()
