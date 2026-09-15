"""Privacy and coordinate-calibration regressions for the dashboard."""
import unittest

import numpy as np

from rendering import Dashboard


class RenderingTests(unittest.TestCase):
    def test_untracked_person_is_masked_in_complete_output(self):
        sensitive_color = np.array([255, 0, 255], dtype=np.uint8)
        frame = np.full((100, 80, 3), sensitive_color, dtype=np.uint8)
        original = frame.copy()
        dashboard = Dashboard([[0, .5], [1, .5]])
        output = dashboard.render(
            frame, [{"xyxy": [-2, -2, 83, 103], "track_id": None, "confidence": .9}],
            {"occupancy": 0}, fps=0, frame_index=1)
        self.assertFalse(np.any(np.all(output == sensitive_color, axis=-1)),
                         "Source image pixels leaked into the final dashboard")
        np.testing.assert_array_equal(frame, original)
        self.assertEqual(output.shape, (820, 1360, 3))

    def test_solid_mask_covers_box_and_padding(self):
        frame = np.full((120, 160, 3), 255, dtype=np.uint8)
        dashboard = Dashboard([[0, .5], [1, .5]])
        masked, _ = dashboard._mask(frame, [{"xyxy": [40.5, 20.5, 90.5, 100.5], "track_id": None}])
        self.assertTrue(np.all(masked[16:105, 36:95] == (46, 53, 48)))
        self.assertTrue(np.all(masked[0, 0] == 255))

    def test_floor_projection_maps_corners_and_excludes_outside(self):
        quad = np.array([[.2, .2], [.8, .2], [.95, .95], [.05, .95]], np.float32)
        dashboard = Dashboard([[0, .5], [1, .5]], floor_quad=quad)
        for original, expected in zip(quad, [[0, 0], [1, 0], [1, 1], [0, 1]]):
            np.testing.assert_allclose(dashboard._map_point(original), expected, atol=1e-6)
        self.assertIsNone(dashboard._map_point(np.array([0, 0], np.float32)))

    def test_crossed_floor_polygon_is_rejected(self):
        with self.assertRaises(ValueError):
            Dashboard([[0, .5], [1, .5]], floor_quad=[[0, 0], [1, 1], [1, 0], [0, 1]])


if __name__ == "__main__":
    unittest.main()
