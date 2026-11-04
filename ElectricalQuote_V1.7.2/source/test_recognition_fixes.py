"""Focused regressions for known recognition/counting failures; no OCR binary needed."""
import unittest
from unittest.mock import patch

from PIL import Image

from compact_v153 import recognize_compact
from incoming_v153 import recognize_incoming
from vertical_recognition_v16 import _breakers_from_text, recognize_vertical
from surge_recognition_v17 import (
    _extract_anchors, _merge_anchors, _entity_crop_box,
    recognize_surge, surge_pair_warnings,
)


def ocr_data(words):
    """Build the public Tesseract DICT shape from (text,x,y,w,h) labels."""
    result={key:[] for key in ('text','left','top','width','height','conf','block_num','par_num','line_num')}
    for index,(text,x,y,w,h) in enumerate(words,1):
        for key,value in zip(('text','left','top','width','height','conf','block_num','par_num','line_num'),
                             (text,x,y,w,h,95,1,1,index)):
            result[key].append(value)
    return result


class BreakerRecognitionTests(unittest.TestCase):
    def test_rcbo_keyword_survives_numeric_ocr_correction(self):
        cases={
            'RCBO 2P C20A':('RCBO','RCBO-C20A/2P'),
            'RCBO 4P 63A':('RCBO','RCBO-63A/4P'),
            'RCB0 1P + N C2OA':('RCBO','RCBO-C20A/1P+N'),
            'MCCB 3P 63O In=630A':('MCCB','MCCB-630A/3P'),
            'MCB 2P C20A':('MCB','MCB-C20A/2P'),
        }
        for text,expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(_breakers_from_text(text),expected)

    def test_incoming_preserves_neutral_pole(self):
        data=ocr_data([('RCBO-C20A/1P+N',100,100,120,20)])
        with patch('pytesseract.image_to_data',return_value=data), \
             patch('pytesseract.image_to_string',return_value='RCBO-C20A/1P+N'):
            row=recognize_incoming(Image.new('RGB',(1000,1000),'white'))
        self.assertEqual(row['spec'],'RCBO-C20A/1P+N')
        self.assertEqual(row['qty'],1)

    def test_compact_preserves_neutral_and_tm_model(self):
        data=ocr_data([('MCB-C20A/1P+N',10,30,180,20),
                       ('MCCB-TM-250A/4P',10,80,180,20)])
        with patch('pytesseract.image_to_data',return_value=data):
            rows,_=recognize_compact(Image.new('RGB',(1000,600),'white'),1,'test')
        self.assertEqual([r['spec'] for r in rows],['MCB-C20A/1P+N','MCCB-TM-250A/4P'])

    def test_unreadable_column_is_review_item_without_inventing_breaker(self):
        columns=[(100,250),(250,400),(400,550)]
        # Title, incoming, first breaker, auxiliary column (two OCR passes), third breaker.
        readings=['1AP-1','','RCBO 2P C20A','AUX','AUX','MCB 1P+N C16A']
        with patch('vertical_recognition_v16.find_vertical_columns',return_value=(columns,{'reason':'test'})), \
             patch('pytesseract.image_to_string',side_effect=readings):
            rows,diag=recognize_vertical(Image.new('RGB',(1000,1000),'white'))
        devices=[r for r in rows if r.get('record_role')=='feeder']
        unknown=[r for r in rows if r.get('record_role')=='unresolved_branch']
        self.assertEqual([r['spec'] for r in devices],['RCBO-C20A/2P','MCB-C16A/1P+N'])
        self.assertEqual(len(unknown),1)
        self.assertIsNone(unknown[0]['qty'])
        self.assertFalse(unknown[0]['quantity_verified'])
        self.assertEqual(unknown[0]['kind'],'其他')
        self.assertEqual(diag['observed_breakers'],2)
        self.assertEqual(diag['unresolved_branches'],1)


class SurgeRecognitionTests(unittest.TestCase):
    def test_generic_label_next_to_full_model_is_an_independent_entity(self):
        data=ocr_data([('HKPD-B80/420/4P',10,20,160,16),('SPD',300,20,50,16)])
        data['line_num']=[1,1]
        anchors=_extract_anchors(data)
        self.assertEqual(len(anchors),2)
        self.assertEqual({a['raw'] for a in anchors},{'HKPD-B80/420/4P','SPD'})

    def test_fragmented_model_words_follow_horizontal_order_not_glyph_height(self):
        data=ocr_data([('HKPD-',10,22,55,18),('SCB2',70,20,45,20),('/80/4P',120,21,70,18)])
        data['line_num']=[1,1,1]
        anchors=_extract_anchors(data)
        self.assertEqual(len(anchors),1)
        from surge_recognition_v17 import parse_surge_text
        self.assertEqual(parse_surge_text(anchors[0]['raw'])['scb_model'],'HKPD-SCB2/80/4P')
        self.assertEqual(anchors[0]['box'],[10.0,20.0,190.0,40.0])

    def test_repeated_ocr_fuses_same_position_but_retains_identical_devices(self):
        data=ocr_data([('HKPD-B80/420/4P',10,20,160,16),
                       ('HKPD-B80/420/4P',300,20,160,16)])
        first=_extract_anchors(data,(220,780))
        repeated=_extract_anchors(data,(221,781))
        observed=_merge_anchors(first+repeated)
        self.assertEqual(len(observed),2)
        self.assertTrue(all(a['kind']=='浪涌保护器' for a in observed))
        self.assertEqual({a['box'][0] for a in observed},{230,520})

    def test_local_parameter_area_excludes_adjacent_same_kind_device(self):
        anchors=_extract_anchors(ocr_data([
            ('HKPD-B40/385/4P',10,30,160,16),
            ('HKPD-B80/420/4P',330,30,160,16),
        ]),(220,780))
        first=_entity_crop_box(anchors[0],anchors,(1000,1000),(220,780,840,1000))
        second=_entity_crop_box(anchors[1],anchors,(1000,1000),(220,780,840,1000))
        self.assertLessEqual(first[2],second[0])
        self.assertLess(first[2],anchors[1]['box'][0])
        self.assertGreater(second[0],anchors[0]['box'][2])

    def test_two_spatial_pairs_retain_separate_parameters_and_quantities(self):
        from PIL import ImageDraw
        image=Image.new('RGB',(1000,1000),'white')
        draw=ImageDraw.Draw(image)
        draw.rectangle((0,0,99,99),fill='red')
        draw.rectangle((100,0,199,99),fill='blue')
        small='HKPD-SCB2/40/4P HKPD-B40/385/4P T2 Imax=40kA Uc=385V'
        large='HKPD-SCB2/80/4P HKPD-B80/420/4P T1 Imax=80kA Uc=420V'
        data=ocr_data([
            ('HKPD-SCB2/40/4P',10,5,170,16),('HKPD-B40/385/4P',10,40,170,16),
            ('HKPD-SCB2/80/4P',330,5,170,16),('HKPD-B80/420/4P',330,40,170,16),
        ])
        def read(crop,**kwargs):
            if crop.size!=(100,100):return small+'\n'+large
            return small if crop.getpixel((50,50))==(255,0,0) else large
        def local(anchor,*args):
            return (0,0,100,100) if anchor['box'][0]<500 else (100,0,200,100)
        with patch('pytesseract.image_to_data',return_value=data), \
             patch('pytesseract.image_to_string',side_effect=read), \
             patch('surge_recognition_v17._entity_crop_box',side_effect=local):
            rows,warnings=recognize_surge(image,[],1,'CAB')
        spd=[r for r in rows if r['kind']=='浪涌保护器']
        scb=[r for r in rows if r['kind']=='浪涌后备保护器']
        self.assertEqual(len(spd),2)
        self.assertEqual(len(scb),2)
        self.assertEqual(sum(r['qty'] for r in spd),2)
        self.assertEqual({(r['surge_params']['imax_ka'],r['surge_params']['uc_v'],r['surge_params']['spd_type'])
                          for r in spd},{(40.0,385.0,'T2'),(80.0,420.0,'T1')})
        self.assertEqual(warnings,[])

    def test_text_only_reread_does_not_shrink_existing_counts_or_silence_warning(self):
        old=[{'kind':'浪涌保护器','qty':2,'status':'待核对','spec':'原记录SPD'},
             {'kind':'浪涌后备保护器','qty':2,'status':'待核对','spec':'原记录SCB'}]
        text='HKPD-SCB2/80/4P HKPD-B80/420/4P T2 Imax=80kA Uc=420V'
        with patch('pytesseract.image_to_data',return_value=ocr_data([])), \
             patch('pytesseract.image_to_string',return_value=text):
            rows,warnings=recognize_surge(Image.new('RGB',(1000,1000),'white'),old,1,'CAB')
        self.assertEqual([r['qty'] for r in rows],[2,2])
        self.assertTrue(warnings)
        self.assertTrue(all(r.get('quantity_ambiguous') for r in rows))

    def test_single_text_only_paragraph_remains_supported(self):
        text='HKPD-SCB2/80/4P HKPD-B80/420/4P T2 Imax=80kA Uc=420V'
        with patch('pytesseract.image_to_data',return_value=ocr_data([])), \
             patch('pytesseract.image_to_string',return_value=text):
            rows,warnings=recognize_surge(Image.new('RGB',(1000,1000),'white'),[],1,'CAB')
        self.assertEqual(len(rows),2)
        self.assertTrue(all(r['qty']==1 for r in rows))
        self.assertEqual(warnings,[])
        spd=next(r for r in rows if r['kind']=='浪涌保护器')
        self.assertEqual(spd['surge_params']['imax_ka'],80.0)

    def test_unknown_quantity_is_not_treated_as_a_verified_pair(self):
        warnings=surge_pair_warnings([{'kind':'浪涌保护器','qty':None},
                                     {'kind':'浪涌后备保护器','qty':None}])
        self.assertTrue(warnings)

    def test_neighbor_model_cannot_supply_an_anchors_parameters(self):
        data=ocr_data([('HKPD-B40/385/4P',10,30,170,16)])
        wrong='HKPD-B80/420/4P T1 Imax=80kA Uc=420V'
        with patch('pytesseract.image_to_data',return_value=data), \
             patch('pytesseract.image_to_string',return_value=wrong), \
             patch('surge_recognition_v17._detect_t_glyph',return_value=('',None)):
            rows,_=recognize_surge(Image.new('RGB',(1000,1000),'white'),[],1,'CAB')
        spd=next(r for r in rows if r['kind']=='浪涌保护器')
        self.assertEqual(spd['surge_params']['spd_model'],'HKPD-B40/385/4P')
        self.assertIsNone(spd['surge_params']['imax_ka'])
        self.assertIsNone(spd['surge_params']['uc_v'])
        self.assertIn('冲突',spd['remark'])

    def test_unlocated_multiple_models_remain_unknown_without_mixed_parameters(self):
        text=('HKPD-B40/385/4P T2 Imax=40kA Uc=385V\n'
              'HKPD-B80/420/4P T1 Imax=80kA Uc=420V')
        with patch('pytesseract.image_to_data',return_value=ocr_data([])), \
             patch('pytesseract.image_to_string',return_value=text):
            rows,warnings=recognize_surge(Image.new('RGB',(1000,1000),'white'),[],1,'CAB')
        self.assertEqual(len(rows),1)
        self.assertIsNone(rows[0]['qty'])
        self.assertIsNone(rows[0]['surge_params']['imax_ka'])
        self.assertEqual(rows[0]['surge_params']['spd_model'],'')
        self.assertTrue(warnings)


if __name__=='__main__':
    unittest.main()
