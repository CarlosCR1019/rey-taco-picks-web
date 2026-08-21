import unittest

from backend.payment_review import classify_receipt


class PaymentReviewTests(unittest.TestCase):
    def test_ocr_never_approves_membership(self):
        result = classify_receipt("BBVA transferencia exitosa 299 Rey Taco")
        self.assertEqual(result.status, "pending_review")
        self.assertTrue(result.detected_amount)
        self.assertTrue(result.detected_bank)

    def test_empty_ocr_still_requires_review(self):
        result = classify_receipt("")
        self.assertEqual(result.status, "pending_review")
        self.assertFalse(result.detected_amount)


if __name__ == "__main__":
    unittest.main()
