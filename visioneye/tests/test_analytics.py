"""Run from visioneye with: python -m unittest discover -s tests -v."""

import unittest

from analytics import DirectionalCounter


class DirectionalCounterTests(unittest.TestCase):
    def make_counter(self, **kwargs):
        return DirectionalCounter(((0, 0), (100, 0)), **kwargs)

    def feed(self, counter, path, track_id=7, start=0):
        events = []
        for frame, point in enumerate(path, start=start):
            events.extend(counter.update({track_id: point}, frame, frame / 30.0))
        return events

    def test_crossing_both_directions_and_event_metadata(self):
        counter = self.make_counter()
        events = self.feed(counter, [(50, -20), (50, 20), (50, -20)])
        self.assertEqual([event["direction"] for event in events], ["IN", "OUT"])
        self.assertEqual(events[0], {
            "track_id": 7, "direction": "IN", "frame": 1, "timestamp": 1 / 30.0,
        })
        self.assertEqual((counter.total_in, counter.total_out, counter.occupancy), (1, 1, 0))

    def test_in_side_and_gate_orientation(self):
        counter = self.make_counter(in_side=-1, initial_occupancy=2)
        events = self.feed(counter, [(50, -20), (50, 20)])
        self.assertEqual(events[0]["direction"], "OUT")
        self.assertEqual(counter.occupancy, 1)
        reverse = DirectionalCounter(((100, 0), (0, 0)))
        events = self.feed(reverse, [(50, 20), (50, -20)])
        self.assertEqual(events[0]["direction"], "IN")

    def test_crossing_line_extension_does_not_count(self):
        for x in (-1, 101):
            with self.subTest(x=x):
                counter = self.make_counter()
                events = self.feed(counter, [(x, -20), (x, 20), (50, 20)])
                self.assertEqual(events, [])

    def test_endpoints_are_part_of_gate(self):
        for x in (0, 100):
            with self.subTest(x=x):
                self.assertEqual(len(self.feed(self.make_counter(), [(x, -20), (x, 20)])), 1)

    def test_hysteresis_ignores_jitter_and_confirms_once(self):
        counter = self.make_counter(hysteresis=8)
        events = self.feed(counter, [
            (50, -20), (50, -2), (50, 3), (50, -1), (50, 2), (50, 7),
            (50, 12), (50, 2), (50, -3), (50, 3), (50, 20),
        ])
        self.assertEqual([event["direction"] for event in events], ["IN"])
        self.assertEqual(events[0]["frame"], 6)

    def test_initial_points_inside_band_do_not_count(self):
        events = self.feed(self.make_counter(), [(50, -2), (50, 3), (50, 20)])
        self.assertEqual(events, [])

    def test_same_track_can_repeatedly_enter_and_exit(self):
        counter = self.make_counter()
        events = self.feed(counter, [(50, y) for y in (-20, 20, -20, 20, -20, 20)])
        self.assertEqual([event["direction"] for event in events], ["IN", "OUT", "IN", "OUT", "IN"])
        self.assertEqual(counter.occupancy, 1)

    def test_long_observation_gap_reseeds_track(self):
        counter = self.make_counter(max_gap_frames=3)
        counter.update({7: (50, -20)}, 0, 0)
        self.assertEqual(counter.update({7: (50, 20)}, 4, 1), [])
        self.assertEqual(counter.update({7: (50, -20)}, 5, 2)[0]["direction"], "OUT")

    def test_short_gap_still_counts_and_ttl_cleans_memory(self):
        counter = self.make_counter(max_gap_frames=3, ttl_frames=5)
        counter.update({7: (50, -20)}, 0, 0)
        counter.update({}, 1, 1)
        self.assertEqual(len(counter.update({7: (50, 20)}, 3, 2)), 1)
        counter.update({}, 9, 3)
        self.assertEqual(counter.stats()["active_tracks"], 0)
        self.assertEqual(counter.update({7: (50, -20)}, 10, 4), [])

    def test_unmatched_out_is_exposed_without_negative_display(self):
        counter = self.make_counter()
        self.feed(counter, [(50, 20), (50, -20)])
        self.assertEqual(counter.raw_occupancy, -1)
        self.assertEqual(counter.occupancy, 0)
        self.assertTrue(counter.underflow)
        counter.update({7: (50, 20)}, 2, 2)
        self.assertEqual(counter.raw_occupancy, 0)
        self.assertFalse(counter.underflow)

    def test_duplicate_frames_do_not_count_twice(self):
        counter = self.make_counter()
        counter.update({7: (50, -20)}, 0, 0)
        counter.update({7: (50, 20)}, 1, 1)
        self.assertEqual(counter.update({7: (50, -20)}, 1, 1), [])
        self.assertEqual(counter.total_out, 0)
        self.assertEqual(len(counter.update({7: (50, -20)}, 2, 2)), 1)
        with self.assertRaises(ValueError):
            counter.update({}, 1, 3)

    def test_actual_path_crossing_used_not_stable_point_shortcut(self):
        counter = self.make_counter()
        # Cross the extension at x > 100, then travel inside the band before
        # confirming the new side. The stable-to-stable chord hits the gate,
        # but the actual sampled path does not.
        events = self.feed(counter, [(150, -20), (150, 2), (50, 2), (50, 20)])
        self.assertEqual(events, [])

    def test_cross_on_gate_then_confirm_beyond_endpoint(self):
        counter = self.make_counter()
        events = self.feed(counter, [(50, -20), (50, 2), (150, 2), (150, 20)])
        self.assertEqual([event["direction"] for event in events], ["IN"])

    def test_exact_line_touch_requires_opposite_side_departure(self):
        counter = self.make_counter()
        events = self.feed(counter, [(50, -20), (50, 0), (50, -20), (50, 0), (50, 20)])
        self.assertEqual([event["direction"] for event in events], ["IN"])

    def test_diagonal_gate_uses_perpendicular_pixel_distance(self):
        counter = DirectionalCounter(((0, 0), (100, 100)), hysteresis=8)
        events = self.feed(counter, [(60, 40), (50, 50), (40, 60)])
        self.assertEqual(events[0]["direction"], "IN")

    def test_multiple_ids_are_independent(self):
        counter = self.make_counter(initial_occupancy=1)
        counter.update({1: (30, -20), 2: (70, 20)}, 0, 0)
        events = counter.update({1: (30, 20), 2: (70, -20)}, 1, 1)
        self.assertEqual({(event["track_id"], event["direction"]) for event in events}, {(1, "IN"), (2, "OUT")})
        self.assertEqual(counter.occupancy, 1)

    def test_invalid_geometry_and_config_rejected(self):
        for line in [((0, 0), (0, 0)), ((0, 0), (float("nan"), 1))]:
            with self.assertRaises(ValueError):
                DirectionalCounter(line)
        for kwargs in [{"in_side": 0}, {"hysteresis": -1}, {"hysteresis": float("inf")}, {"initial_occupancy": -1}, {"max_gap_frames": -1}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.make_counter(**kwargs)

    def test_invalid_frame_is_atomic(self):
        counter = self.make_counter()
        counter.update({7: (50, -20)}, 0, 0)
        with self.assertRaises(ValueError):
            counter.update({7: (50, 20), 8: (float("nan"), 20)}, 1, 1)
        self.assertEqual(counter.total_in, 0)
        self.assertEqual(len(counter.update({7: (50, 20)}, 1, 1)), 1)


if __name__ == "__main__":
    unittest.main()
