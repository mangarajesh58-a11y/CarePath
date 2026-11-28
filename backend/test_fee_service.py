"""
Comprehensive Test Suite for Q-Arovia Dynamic Platform Fee, GST & Payment Gateway Fee Calculation.
"""
import unittest
from decimal import Decimal
from fee_service import calculate_dynamic_fees, to_decimal

class TestDynamicFeeCalculation(unittest.TestCase):

    def test_section_3_spec_example(self):
        """
        Verify Section 3 Exact Specification Table:
        Hospital Token Fee: ₹100.00
        Q-Arovia Platform Fee: ₹10.00
        GST (18% on Platform Fee): ₹1.80
        Payment Gateway (2% + 18% GST): ₹2.36
        Total Extra Fee: ₹14.16
        Final Patient Payment: ₹114.16
        """
        config = {
            "platform_fee": 10.00,
            "gst_percentage": 18.00,
            "gateway_fee_percentage": 2.00,
            "gateway_fee_gst": 18.00,
            "gateway_fee_basis": "hospital_fee",
            "pass_gateway_fee_to_patient": True,
            "version": 1
        }
        res = calculate_dynamic_fees(100.00, fee_config=config)
        self.assertEqual(res.hospital_token_fee, Decimal("100.00"))
        self.assertEqual(res.platform_fee, Decimal("10.00"))
        self.assertEqual(res.gst_amount, Decimal("1.80"))
        self.assertEqual(res.gateway_fee_amount, Decimal("2.36"))
        self.assertEqual(res.total_extra_fee, Decimal("14.16"))
        self.assertEqual(res.final_amount, Decimal("114.16"))

    def test_platform_fee_variations(self):
        """
        Section 9: Test platform fee values: ₹5, ₹10, ₹15, ₹20, ₹25, ₹50, ₹100.
        Verify GST and gateway fees recalculate correctly for every value.
        """
        expected = {
            5: {"gst": Decimal("0.90"), "gw": Decimal("2.36"), "extra": Decimal("8.26"), "final": Decimal("108.26")},
            10: {"gst": Decimal("1.80"), "gw": Decimal("2.36"), "extra": Decimal("14.16"), "final": Decimal("114.16")},
            15: {"gst": Decimal("2.70"), "gw": Decimal("2.36"), "extra": Decimal("20.06"), "final": Decimal("120.06")},
            20: {"gst": Decimal("3.60"), "gw": Decimal("2.36"), "extra": Decimal("25.96"), "final": Decimal("125.96")},
            25: {"gst": Decimal("4.50"), "gw": Decimal("2.36"), "extra": Decimal("31.86"), "final": Decimal("131.86")},
            50: {"gst": Decimal("9.00"), "gw": Decimal("2.36"), "extra": Decimal("61.36"), "final": Decimal("161.36")},
            100: {"gst": Decimal("18.00"), "gw": Decimal("2.36"), "extra": Decimal("120.36"), "final": Decimal("220.36")},
        }
        for pf, exp in expected.items():
            config = {
                "platform_fee": pf,
                "gst_percentage": 18.00,
                "gateway_fee_percentage": 2.00,
                "gateway_fee_gst": 18.00,
                "gateway_fee_basis": "hospital_fee",
                "pass_gateway_fee_to_patient": True,
            }
            res = calculate_dynamic_fees(100.00, fee_config=config)
            self.assertEqual(res.platform_fee, Decimal(str(pf)).quantize(Decimal("0.01")))
            self.assertEqual(res.gst_amount, exp["gst"], f"Failed GST for PF {pf}")
            self.assertEqual(res.gateway_fee_amount, exp["gw"], f"Failed GW for PF {pf}")
            self.assertEqual(res.total_extra_fee, exp["extra"], f"Failed Extra for PF {pf}")
            self.assertEqual(res.final_amount, exp["final"], f"Failed Final for PF {pf}")

    def test_zero_platform_fee(self):
        """Test zero platform fee configuration."""
        config = {
            "platform_fee": 0.00,
            "gst_percentage": 18.00,
            "gateway_fee_percentage": 2.00,
            "gateway_fee_gst": 18.00,
            "gateway_fee_basis": "hospital_fee",
            "pass_gateway_fee_to_patient": True,
        }
        res = calculate_dynamic_fees(100.00, fee_config=config)
        self.assertEqual(res.platform_fee, Decimal("0.00"))
        self.assertEqual(res.gst_amount, Decimal("0.00"))
        self.assertEqual(res.gateway_fee_amount, Decimal("2.36"))
        self.assertEqual(res.total_extra_fee, Decimal("2.36"))
        self.assertEqual(res.final_amount, Decimal("102.36"))

    def test_decimal_platform_fee(self):
        """Test decimal platform fee (e.g. ₹12.50)."""
        config = {
            "platform_fee": 12.50,
            "gst_percentage": 18.00,
            "gateway_fee_percentage": 2.00,
            "gateway_fee_gst": 18.00,
            "gateway_fee_basis": "hospital_fee",
            "pass_gateway_fee_to_patient": True,
        }
        res = calculate_dynamic_fees(100.00, fee_config=config)
        # 12.50 * 0.18 = 2.25
        self.assertEqual(res.platform_fee, Decimal("12.50"))
        self.assertEqual(res.gst_amount, Decimal("2.25"))
        self.assertEqual(res.gateway_fee_amount, Decimal("2.36"))
        self.assertEqual(res.total_extra_fee, Decimal("17.11"))
        self.assertEqual(res.final_amount, Decimal("117.11"))

    def test_gateway_fee_disabled(self):
        """Test when gateway fee recovery from patients is disabled."""
        config = {
            "platform_fee": 10.00,
            "gst_percentage": 18.00,
            "gateway_fee_percentage": 2.00,
            "gateway_fee_gst": 18.00,
            "gateway_fee_basis": "hospital_fee",
            "pass_gateway_fee_to_patient": False,
        }
        res = calculate_dynamic_fees(100.00, fee_config=config)
        self.assertEqual(res.gateway_fee_amount, Decimal("0.00"))
        self.assertEqual(res.total_extra_fee, Decimal("11.80"))
        self.assertEqual(res.final_amount, Decimal("111.80"))

    def test_rate_changes(self):
        """Test custom GST rate (12%) and custom gateway fee (1.8% + 18% GST)."""
        config = {
            "platform_fee": 20.00,
            "gst_percentage": 12.00,
            "gateway_fee_percentage": 1.80,
            "gateway_fee_gst": 18.00,
            "gateway_fee_basis": "hospital_fee",
            "pass_gateway_fee_to_patient": True,
        }
        res = calculate_dynamic_fees(200.00, fee_config=config)
        # GST: 20 * 0.12 = 2.40
        # GW base: 200 * 0.018 = 3.60; GW GST: 3.60 * 0.18 = 0.648 -> 0.65; GW total: 4.25
        # Total extra: 20 + 2.40 + 4.25 = 26.65
        # Final: 226.65
        self.assertEqual(res.gst_amount, Decimal("2.40"))
        self.assertEqual(res.gateway_fee_amount, Decimal("4.25"))
        self.assertEqual(res.total_extra_fee, Decimal("26.65"))
        self.assertEqual(res.final_amount, Decimal("226.65"))

    def test_subtotal_gateway_basis(self):
        """Test calculation when gateway fee basis is subtotal (hospital fee + platform fee + GST)."""
        config = {
            "platform_fee": 10.00,
            "gst_percentage": 18.00,
            "gateway_fee_percentage": 2.00,
            "gateway_fee_gst": 18.00,
            "gateway_fee_basis": "subtotal",
            "pass_gateway_fee_to_patient": True,
        }
        res = calculate_dynamic_fees(100.00, fee_config=config)
        # Subtotal: 100 + 10 + 1.80 = 111.80
        # GW base: 111.80 * 0.02 = 2.236 -> 2.24
        # GW GST: 2.24 * 0.18 = 0.4032 -> 0.40
        # GW amount: 2.24 + 0.40 = 2.64
        # Total extra: 10 + 1.80 + 2.64 = 14.44
        # Final: 114.44
        self.assertEqual(res.gst_amount, Decimal("1.80"))
        self.assertEqual(res.gateway_fee_amount, Decimal("2.64"))
        self.assertEqual(res.total_extra_fee, Decimal("14.44"))
        self.assertEqual(res.final_amount, Decimal("114.44"))


if __name__ == "__main__":
    unittest.main()
