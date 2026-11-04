"""Regression cases for direction, grouped feeders and observed label assignment."""
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from feeder_geometry_v152 import detect_feeder_lines, read_drawn_tags
from orientation_v16 import detect_rotation, unrotate_box
from precise_locator_v161 import locate_observed_printed_labels


class DirectionTests(unittest.TestCase):
    def test_unreadable_titles_keep_original(self):
        with patch('pytesseract.image_to_string', return_value=''):
            turns, diagnostic = detect_rotation(Image.new('RGB', (100, 200)))
        self.assertEqual(turns, 0)
        self.assertEqual(diagnostic['rotation'], 0)
        self.assertEqual(diagnostic['confidence'], '低')

    def test_equal_nonzero_scores_require_review(self):
        with patch('pytesseract.image_to_string', side_effect=['', 'PANEL NO', 'PANEL NO', '']):
            turns, diagnostic = detect_rotation(Image.new('RGB', (100, 200)))
        self.assertEqual(turns, 0)
        self.assertIn('得分相同', diagnostic['reason'])

    def test_unique_supported_rotation_is_applied(self):
        with patch('pytesseract.image_to_string', side_effect=['', 'PANEL NO', '', '']):
            turns, _ = detect_rotation(Image.new('RGB', (100, 200)))
        self.assertEqual(turns, 1)


class FeederGroupTests(unittest.TestCase):
    def detect(self, positions):
        image = Image.new('RGB', (1000, 1000), 'white')
        draw = ImageDraw.Draw(image)
        for y in positions:
            draw.line((300, y, 800, y), fill='black', width=3)
        return detect_feeder_lines(image)

    def test_separated_groups_are_both_retained(self):
        positions = [100, 150, 200, 250, 400, 450, 500, 550]
        detected, diagnostic = self.detect(positions)
        self.assertEqual(detected, positions)
        self.assertEqual(len(diagnostic['groups']), 2)
        self.assertTrue(diagnostic['warnings'])

    def test_changed_group_pitch_is_retained(self):
        positions = [100, 150, 200, 250, 400, 480, 560, 640]
        detected, _ = self.detect(positions)
        self.assertEqual(detected, positions)

    def test_pitch_change_without_a_blank_group_gap(self):
        positions = [100, 150, 200, 250, 330, 410, 490]
        detected, _ = self.detect(positions)
        self.assertEqual(detected, positions)

    def test_three_point_group_can_share_the_previous_endpoint(self):
        positions = [100, 150, 200, 250, 330, 410]
        detected, diagnostic = self.detect(positions)
        self.assertEqual(detected, positions)
        self.assertEqual(diagnostic['groups'][1]['lines'], [330, 410])
        self.assertEqual(diagnostic['groups'][1]['pitch'], 80)

    def test_unassigned_end_line_is_reported(self):
        detected, diagnostic = self.detect([100, 150, 200, 250, 400])
        self.assertEqual(detected, [100, 150, 200, 250])
        self.assertIn(400, diagnostic['unassigned_lines'])
        self.assertTrue(diagnostic['warnings'])

    def test_isolated_surge_and_sheet_edges_are_excluded(self):
        feeders = [100, 150, 200, 250]
        detected, _ = self.detect([1, 30] + feeders + [370, 550, 999])
        self.assertEqual(detected, feeders)

    def test_printed_tag_crops_use_each_groups_pitch(self):
        lines = [100, 150, 200, 400, 500, 600]
        groups = [{'lines': lines[:3], 'pitch': 50}, {'lines': lines[3:], 'pitch': 100}]
        heights = []

        def read(crop, **_):
            heights.append(crop.height)
            return f'W{len(heights)}'

        with patch('feeder_geometry_v152.find_tag_column', return_value=(100, 200)), \
                patch('pytesseract.image_to_string', side_effect=read):
            tags, _ = read_drawn_tags(Image.new('RGB', (1000, 1000)), lines, groups)
        self.assertEqual(tags, [f'W{i}' for i in range(1, 7)])
        self.assertEqual(heights, [74, 74, 74, 148, 148, 148])


class PrintedLocationTests(unittest.TestCase):
    @staticmethod
    def ocr(words):
        return {
            'text': [word for word, _, _ in words],
            'left': [x for _, x, _ in words],
            'top': [y for _, _, y in words],
            'width': [120 for _ in words],
            'height': [12 for _ in words],
            'conf': [90 for _ in words],
        }

    def locate(self, rows, words, turns=0):
        with patch('pytesseract.image_to_data', return_value=self.ocr(words)):
            return locate_observed_printed_labels(
                Image.new('RGB', (1000, 1000), 'white'), rows, turns, unrotate_box)

    def test_same_word_in_two_psm_passes_cannot_prove_two_devices(self):
        rows = [{'kind': '微型断路器', 'spec': 'C16A/1P'} for _ in range(2)]
        self.locate(rows, [('MCB-C16A/1P', 200, 200)])
        self.assertEqual(sum(bool(row.get('rel_boxes')) for row in rows), 1)

    def test_missing_feeder_label_does_not_steal_its_neighbors_label(self):
        rows = [{'kind': '微型断路器', 'spec': 'C16A/1P', '_anchor_corrected_y': y}
                for y in (.3, .4, .5)]
        self.locate(rows, [('MCB-C16A/1P', 250, 254), ('MCB-C16A/1P', 250, 454)])
        self.assertTrue(rows[0].get('rel_boxes'))
        self.assertFalse(rows[1].get('rel_boxes'))
        self.assertTrue(rows[2].get('rel_boxes'))

    def test_vertical_branch_search_stays_in_its_column_after_rotation(self):
        corrected = [[.15, .1, .35, .4], [.6, .1, .8, .4]]
        rows = [{'kind': '塑壳断路器', 'spec': '200A/3P',
                 'rel_boxes': [unrotate_box(box, 1)]} for box in corrected]
        self.locate(rows, [('MCCB-200A/3P', 610, 200)], turns=1)
        self.assertFalse(rows[0].get('rel_boxes'))
        self.assertTrue(rows[1].get('rel_boxes'))

    def test_different_currents_with_shared_digits_do_not_match(self):
        rows = [{'kind': '微型断路器', 'spec': 'C16A/1P'},
                {'kind': '微型断路器', 'spec': 'C160A/1P'}]
        self.locate(rows, [('MCB-C160A/1P', 250, 200)])
        self.assertFalse(rows[0].get('rel_boxes'))
        self.assertTrue(rows[1].get('rel_boxes'))

    def test_group_gap_does_not_expand_the_label_search(self):
        rows = [{'kind': '微型断路器', 'spec': 'C16A/1P',
                 '_anchor_corrected_y': y, 'pdf_rel_pitch': .1} for y in (.2, .8)]
        self.locate(rows, [('MCB-C16A/1P', 250, 450)])
        self.assertFalse(any(row.get('rel_boxes') for row in rows))


if __name__ == '__main__':
    unittest.main()
