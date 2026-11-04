# /// script
# requires-python = ">=3.9"
# dependencies = ["pymupdf==2.1", "shapely==2.2.0"]
# ///
"""First-run regressions: unknown quantities, page coverage and provenance."""
import copy
from contextlib import redirect_stdout
import csv
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import measure
import audit
import spec_schema
from test_support import sh


class OutputContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        pdf, geo = cls.root / 'plans.pdf', cls.root / 'geometry.json'
        sh(str(SKILL / 'examples/make_fixture.py'), '--out', str(pdf))
        sh(str(SKILL / 'scripts/extract_geometry.py'), str(pdf), '--pages', 'all', '--out', str(geo))
        cls.fixture = json.loads((SKILL / 'examples/fixture.jobs.json').read_text())
        cls.fixture['source']['pdf'] = str(pdf)
        cls.fixture['geometry'] = str(geo)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def original(self):
        spec = copy.deepcopy(self.fixture)
        spec['assemblies'], spec['pieces'] = [], []
        for name in ('A', 'B'):
            regions = [r for r in spec['regions'] if r['kind'] == 'base' and r['type'] == name]
            spec['assemblies'].append({'assembly_id': name, 'type': name, 'package': 'millwork',
                'quantity_basis': {'mode': 'room_type_count', 'type': name},
                'pieces': ['p:' + r['region_id'] for r in regions]})
            spec['pieces'] += [{'piece_id': 'p:' + r['region_id'], 'assembly_id': name,
                'route': 'geometry', 'region_id': r['region_id']} for r in regions]
        return spec

    def run_job(self, spec):
        job, results, pieces, report, takeoff = [self.root / name for name in
            ('job.json', 'results.json', 'pieces.csv', 'report.md', 'takeoff.csv')]
        job.write_text(json.dumps(spec), encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(measure.main([str(job), '--json', str(results), '--piece-csv', str(pieces),
                '--report', str(report), '--csv', str(takeoff)]), 0)
        with pieces.open(newline='', encoding='utf-8') as stream:
            csv_rows = list(csv.DictReader(stream))
        with takeoff.open(newline='', encoding='utf-8') as stream:
            takeoff_rows = list(csv.DictReader(stream))
        return json.loads(results.read_text()), csv_rows, report.read_text(), takeoff_rows

    def test_unknown_profile_survives_extension_and_exports(self):
        spec = self.original()
        spec['pieces'][0]['edge_runs'] = [
            {'profile': 'eased', 'exposure': 'front', 'length_in': None},
            {'profile': 'polished', 'exposure': 'side', 'length_in': 12}]
        result, rows, report, _ = self.run_job(spec)
        piece = result['piece_boq'][0]
        self.assertEqual(piece['edge_lf_ext'], {'eased': None, 'polished': 3.0})
        self.assertEqual(json.loads(rows[0]['edge_lf_by_profile_xEA']), piece['edge_lf_ext'])
        self.assertIn('eased=BLANK', report)
        self.assertFalse(piece['quantity_complete'])
        self.assertIn('edge_lf_ext:eased', piece['blank_fields'])
        self.assertEqual(result['totals']['known_subtotal_sf'], 168.75)

    def test_unknown_cutouts_stay_null_not_an_empty_map(self):
        result, rows, report, _ = self.run_job(self.original())
        self.assertIsNone(result['piece_boq'][0]['cutouts_ea'])
        self.assertIsNone(result['piece_boq'][0]['cutouts_ea_ext'])
        self.assertEqual(rows[0]['cutouts_ea'], '')
        self.assertEqual(rows[0]['cutouts_ea_xEA'], '')
        self.assertIsNone(result['piece_boq'][0]['splash_detail'])
        self.assertEqual(rows[0]['splash_runs'], '')
        self.assertIn('cutouts_ea', result['piece_boq'][0]['blank_fields'])
        self.assertTrue(any('cutouts_ea' in c['blank_fields'] for c in result['callouts']))
        self.assertTrue(result['property_gaps'])
        self.assertFalse(result['totals']['quantity_complete'])

    def test_declared_none_zero_and_partly_unknown_cutouts_are_distinct(self):
        spec = self.original()
        spec['pieces'][0]['cutouts'] = []
        spec['pieces'][0]['splash_runs'] = []
        spec['pieces'][1]['cutouts'] = [{'kind': 'sink', 'ea': 0}, {'kind': 'tap', 'ea': None}]
        result, rows, report, _ = self.run_job(spec)
        self.assertEqual(result['piece_boq'][0]['cutouts_ea'], {})
        self.assertEqual(result['piece_boq'][1]['cutouts_ea_ext'], {'sink': 0, 'tap': None})
        self.assertEqual(rows[0]['cutouts_ea'], '{}')
        self.assertEqual(result['piece_boq'][0]['splash_detail'], [])
        self.assertEqual(rows[0]['splash_runs'], '[]')
        self.assertIn('none declared', report)
        self.assertIn('tap=BLANK', report)
        for invalid in (-1, 0.5, True):
            broken = self.original()
            broken['pieces'][0]['cutouts'] = [{'kind': 'sink', 'ea': invalid}]
            with self.assertRaises(spec_schema.SpecError):
                self.run_job(broken)

    def test_every_page_has_one_ledger_entry_and_unresolved_is_not_skipped(self):
        spec = self.original()
        spec['scope']['pages'][0].update(disposition='superseded', reason='old schedule')
        spec['scope']['pages'][2].update(disposition='unresolved', reason='detail missing')
        result, _, report, _ = self.run_job(spec)
        pages = [e for e in result['coverage_ledger'] if e['kind'] == 'page']
        self.assertEqual(len(pages), 3)
        self.assertEqual([e['state'] for e in pages], ['superseded', 'measured', 'unresolved'])
        self.assertIn('page 3 unresolved: detail missing', report)
        self.assertNotIn('page 3 intentionally_skipped', report)
        self.assertTrue(any(e['kind'] == 'page' for e in result['scope_incomplete']))

    def test_missing_disposition_and_indexed_sheet_travel_as_unknown_scope(self):
        spec = self.original()
        spec['scope']['pages'].pop()
        spec['sheet_index'] = {'source_id': 'plans', 'page': 1, 'lists': ['A-001', 'A-999']}
        result, _, _, _ = self.run_job(spec)
        missing = [e for e in result['scope_incomplete'] if e['kind'] == 'sheet']
        self.assertEqual([e['sheet'] for e in missing], ['A-999'])
        self.assertEqual(missing[0]['source']['pages'], [1])
        self.assertTrue(missing[0]['blank_fields'])
        self.assertEqual(len([e for e in result['coverage_ledger'] if e['kind'] == 'page']), 3)
        self.assertFalse(result['totals']['project_sf_complete'])
        self.assertEqual(result['totals']['known_subtotal_sf'], 168.75)

    def test_stated_properties_keep_source_pages_and_selection_ids_in_all_views(self):
        spec = self.original()
        piece = spec['pieces'][0]
        piece.update(route='stated', dims_in={'width': 120, 'depth': 30},
                     source_links={'length': {'source_id': 'plans', 'page': 2, 'kind': 'plan', 'word_ids': [29]},
                                   'depth': {'source_id': 'plans', 'page': 3, 'kind': 'section', 'word_ids': [30]}})
        piece.pop('region_id')
        result, rows, report, takeoff = self.run_job(spec)
        meta = result['piece_boq'][0]['region_meta']
        self.assertEqual((meta['source_id'], meta['page'], meta['sheet']), ('plans', 2, 'A-101'))
        self.assertEqual({s['page'] for s in meta['sources']}, {2, 3})
        self.assertEqual(json.loads(rows[0]['source_links'])['length']['word_ids'], [29])
        self.assertIn('p.2 [length]', takeoff[0]['source'])
        self.assertIn('p.3 [depth]', takeoff[0]['source'])
        self.assertIn('plans:A-101 p2 [length]', report)

    def test_unknown_area_does_not_claim_measured_assembly(self):
        spec = self.original()
        spec['pieces'][0].update(route='stated', dims_in={'width': 120, 'depth': None})
        spec['pieces'][0].pop('region_id')
        result, _, _, _ = self.run_job(spec)
        piece, assembly = result['piece_boq'][0], result['assembly_boq'][0]
        self.assertEqual(piece['state'], 'unresolved')
        self.assertEqual(assembly['state'], 'unresolved')
        self.assertEqual(assembly['ea'], 3)
        self.assertEqual(assembly['ea_state'], 'resolved')
        self.assertIsNone(assembly['extended_sf'])

    def test_schedule_prototypes_cover_each_inventoried_room(self):
        result, _, _, _ = self.run_job(self.original())
        rooms = [e for e in result['coverage_ledger'] if e['kind'] == 'room']
        self.assertEqual(len(rooms), 5)
        self.assertTrue(all(e['state'] == 'measured' for e in rooms))
        self.assertTrue(result['totals']['project_sf_complete'])

    def test_pages_are_keyed_by_source_not_page_number(self):
        spec = self.original()
        spec['schema'] = 'countertop-takeoff/v3'
        spec['sources'] = [dict(source_id=sid, kind='pdf', path=spec['source']['pdf'],
                                sha256=spec['source']['sha256']) for sid in ('plans', 'other')]
        spec['geometry'] = {sid: spec['geometry'] for sid in ('plans', 'other')}
        spec.pop('source')
        result, _, _, _ = self.run_job(spec)
        pages = [e for e in result['coverage_ledger'] if e['kind'] == 'page']
        keys = {(e['source']['source_id'], e['source']['pages'][0]) for e in pages}
        self.assertEqual(len(pages), 6)
        self.assertEqual(len(keys), 6)
        self.assertTrue(all(e['state'] == 'unresolved' for e in pages
                            if e['source']['source_id'] == 'other'))

    def test_zero_ea_does_not_turn_an_unknown_property_into_a_zero(self):
        spec = self.original()
        spec['schedule']['variants'] = [{'type': 'A', 'name': 'ADA', 'count': 3,
            'included_in_parent_total': True, 'row_text': '3',
            'word_boxes': copy.deepcopy(spec['schedule']['types'][0]['word_boxes'])}]
        spec['pieces'][0]['edge_runs'] = [{'profile': 'eased', 'exposure': 'front', 'length_in': None}]
        result, _, _, _ = self.run_job(spec)
        piece = result['piece_boq'][0]
        self.assertEqual(piece['ea'], 0)
        self.assertEqual(piece['extension_sf'], 0)
        self.assertEqual(piece['edge_lf_ext'], {'eased': None})
        self.assertIsNone(piece['cutouts_ea_ext'])

    def test_unextracted_pages_still_belong_to_the_inventory(self):
        spec = self.original()
        spec_schema.validate_spec(spec)
        geometry = json.loads(Path(spec['geometry']).read_text())
        geometry['pages'] = geometry['pages'][:1]
        spec['scope']['pages'] = spec['scope']['pages'][:1]
        checks = audit.Audit()
        audit.audit_scope(spec, {'plans': geometry}, checks)
        ledger = audit.build_coverage_ledger(spec, [], checks)
        pages = [e for e in ledger if e['kind'] == 'page']
        self.assertEqual(len(pages), 3)
        self.assertEqual([e['state'] for e in pages], ['included_scope', 'unresolved', 'unresolved'])

    def test_type_unit_area_does_not_sum_enumerated_room_areas(self):
        spec = self.original()
        spec['assemblies'] = [dict(assembly_id=name, type='A', package='millwork',
            quantity_basis={'mode': 'enumerated'}, pieces=['p:' + name]) for name in ('101', '102')]
        spec['pieces'] = [dict(piece_id='p:' + name, assembly_id=name, route='stated',
            dims_in={'width': 72, 'depth': 25.5}) for name in ('101', '102')]
        result, _, _, _ = self.run_job(spec)
        row = next(t for t in result['types'] if t['room_type'] == 'A')
        self.assertEqual(row['extended_sf'], 25.5)
        self.assertEqual(row['sf_per_unit'], 12.75)
        self.assertEqual(row['sf_per_unit_basis'], 'active assembly EA weighted mean')

    def test_run_sources_and_selections_survive_every_export(self):
        spec = self.original()
        source = {'source_id': 'plans', 'page': 2, 'kind': 'detail',
                  'word_ids': [29], 'quoted_text': "10'-0\""}
        piece = spec['pieces'][0]
        piece['splash_runs'] = [{'length_in': 120, 'height_in': 4, 'source': source}]
        piece['edge_runs'] = [{'profile': 'eased', 'exposure': 'front', 'length_in': 120, 'source': source}]
        piece['cutouts'] = [{'kind': 'sink', 'ea': 1, 'source': source}]
        result, rows, report, takeoff = self.run_job(spec)
        row = result['piece_boq'][0]
        self.assertEqual(row['splash_detail'][0]['source'], source)
        self.assertEqual(row['edge_runs'][0]['source'], source)
        self.assertEqual(row['cutout_detail'][0]['source'], source)
        for field in ('splash_runs[0]', 'edge_runs[0]', 'cutouts[0]'):
            self.assertEqual(row['source_links'][field], source)
            self.assertEqual(json.loads(rows[0]['source_links'])[field], source)
            self.assertIn('[' + field + '] words 29', takeoff[0]['source'])
            self.assertIn('[' + field + '] words 29', report)
        self.assertEqual(json.loads(rows[0]['splash_runs'])[0]['source'], source)

    def test_legacy_area_model_does_not_claim_all_property_quantities_complete(self):
        result, _, _, _ = self.run_job(self.original())
        self.assertIs(result['totals']['quantity_complete'], False)
        job, output = self.root / 'legacy.json', self.root / 'legacy-results.json'
        job.write_text(json.dumps(self.fixture), encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(measure.main([str(job), '--json', str(output)]), 0)
        legacy = json.loads(output.read_text())
        self.assertIsNone(legacy['totals']['quantity_complete'])
        self.assertTrue(legacy['totals']['project_sf_complete'])

    def test_unresolved_page_callout_does_not_withhold_known_page_quantities(self):
        spec = self.original()
        spec['scope']['pages'][1].update(disposition='unresolved', reason='partial detail')
        result, _, _, _ = self.run_job(spec)
        callout = next(c for c in result['callouts'] if c['scope'] == 'page plans:2')
        self.assertEqual(callout['blank_fields'], ['unresolved quantities on this page'])
        self.assertEqual(result['piece_boq'][0]['ea'], 3)
        self.assertEqual(result['piece_boq'][0]['sf'], 31.25)


if __name__ == '__main__':
    unittest.main()
