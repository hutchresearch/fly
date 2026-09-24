import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("fly", os.path.join(HERE, "..", "fly.py"))
fly = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fly)

# GPUs_GlobalMemoryMb advertised by each card model (condor_status, 2026-09-24).
ADVERTISED_MIB = {
    "GTX 1650": 3888,
    "GTX 980 Ti": 6062,
    "RTX 4060": 7924,
    "RTX 2080 Ti": 10835,
    "GTX 1080 Ti": 11156,
    "RTX 3060": 12028,
    "RTX 2000 Ada": 16067,
    "RTX 4090": 24201,
    "H100 PCIe": 81124,
}


def matches(expr, mib):
    """Evaluates a require_gpus expression against an advertised memory size."""
    return eval(expr.replace("GlobalMemoryMb", str(mib)).replace("&&", "and"))


def eligible(gpu_mem):
    expr = fly.gpu_constraint(gpu_mem)
    return {card for card, mib in ADVERTISED_MIB.items() if matches(expr, mib)}


SMALL = {"GTX 1650", "GTX 980 Ti", "RTX 4060", "RTX 2080 Ti", "GTX 1080 Ti", "RTX 3060"}


class GpuBandTest(unittest.TestCase):
    def test_no_request_uses_only_small_cards(self):
        self.assertEqual(eligible(0), SMALL)

    def test_nominal_size_matches_its_own_cards(self):
        self.assertEqual(eligible(11), {"RTX 2080 Ti", "GTX 1080 Ti", "RTX 3060"})
        self.assertEqual(eligible(12), {"RTX 3060"})
        self.assertEqual(eligible(4), SMALL)
        self.assertEqual(eligible(8), {"RTX 4060", "RTX 2080 Ti", "GTX 1080 Ti", "RTX 3060"})

    def test_requests_snap_up_to_next_size(self):
        self.assertEqual(fly.gpu_tier(5), 6)
        self.assertEqual(fly.gpu_tier(9), 11)
        self.assertEqual(eligible(9), eligible(11))

    def test_reserved_bands(self):
        self.assertEqual(eligible(13), {"RTX 2000 Ada"})
        self.assertEqual(eligible(16), {"RTX 2000 Ada"})
        self.assertEqual(eligible(17), {"RTX 4090"})
        self.assertEqual(eligible(24), {"RTX 4090"})

    def test_25_does_not_match_24gb_card(self):
        self.assertEqual(fly.gpu_tier(25), 80)
        self.assertEqual(eligible(25), {"H100 PCIe"})

    def test_above_largest_card_is_rejected(self):
        self.assertIsNone(fly.gpu_tier(81))
        self.assertFalse(fly.gpu_request_fits(81))

    def test_fly_pool_fit(self):
        # fly schedules onto the cluster's 11 GB cards only.
        for gpu_mem in (0, 1, 8, 11):
            self.assertTrue(fly.gpu_request_fits(gpu_mem), gpu_mem)
        for gpu_mem in (12, 16, 24, 80):
            self.assertFalse(fly.gpu_request_fits(gpu_mem), gpu_mem)

    def test_constraint_text(self):
        self.assertEqual(fly.gpu_constraint(0), "GlobalMemoryMb < 15200")
        self.assertEqual(fly.gpu_constraint(11), "GlobalMemoryMb >= 10450 && GlobalMemoryMb < 15200")
        self.assertEqual(fly.gpu_constraint(80), "GlobalMemoryMb >= 76000")


if __name__ == "__main__":
    unittest.main()
