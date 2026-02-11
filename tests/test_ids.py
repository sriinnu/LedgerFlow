from __future__ import annotations

import unittest

from ledgerflow.ids import new_id, ulid


class TestIds(unittest.TestCase):
    def test_ulid_shape(self) -> None:
        v = ulid()
        self.assertEqual(len(v), 26)
        self.assertTrue(v.isalnum())

    def test_new_id_prefix(self) -> None:
        v = new_id("tx")
        self.assertTrue(v.startswith("tx_"))

