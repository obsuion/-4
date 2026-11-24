"""No numerical work: exact typed metrics and missing interval qualification."""
from unittest import TestCase
from kaze_study.ninety_metrics import actual,thirty_day_summaries,engineering,UNKNOWN
from tempfile import TemporaryDirectory
from pathlib import Path
from kaze_study.data import canonical,digest
from kaze_study.errors import Refusal

class Metrics(TestCase):
    def test_paid_seed_mechanical_reference_is_bound_by_spec_not_relabelled_as_pilot_root(self):
        with TemporaryDirectory()as temporary:
            evidence=dict(source_identity='S',specification_identity='P',project_identity='original-authored',mass={'total_mass_kg':7},routes=[],thermal_plant=[])
            path=Path(temporary)/'report.json';path.write_bytes(canonical(evidence))
            pr=dict(authored_project_sha256='original-authored',model_mass_kg=7,source_engineering_evidence=evidence,
                source_engineering_report=dict(path=str(path),sha256=digest(path.read_bytes()),bytes=path.stat().st_size))
            view=engineering(pr,source_identity='S',physical_spec_identity='P')
            self.assertEqual(view['mass_properties']['total_mass_kg'],7);self.assertEqual(view['seed_support_duration_seconds'],600)
            with self.assertRaisesRegex(Refusal,'PHYSICAL_BINDING'):engineering(pr,source_identity='S',physical_spec_identity='different-spec')

    def test_credit_does_not_invent_acquisition_delivery_or_refusal_causes(self):
        value=actual(dict(report=dict(totals=dict(credits=0,refused_actions=7,
            forecast_refusals_by_reason={'energy':7}))),start=128,end=200,target=300,role='PRIMARY')
        self.assertEqual(value['score'],0)
        for key in('acquired','delivered','delivered_on_time','actual_refusals_by_reason'):
            self.assertEqual(value[key],UNKNOWN)
        self.assertEqual(value['refusal_total'],7)
        self.assertFalse(value['forecast_refusals_included'])

    def test_exact_rational_sums_and_sampled_electrical_scope_retained(self):
        science=dict(report=dict(totals=dict(sums={'unmet_load_wh':[7,13]},
            battery_port=dict(method='B58_SELECTED_SAMPLED_PORT_REPORT_V1',
                scope='SELECTED_START_HELD_SAMPLES_NOT_CONTINUOUS_BOUNDS',maximum_abs_current_a=1.25,
                maximum_resistance_ohm=.2),wear_start={'battery_retention':1},wear_end={'battery_retention':.99})))
        value=actual(science,start=128,end=300,target=300,role='PRIMARY',declared_mass=8)
        self.assertEqual(value['unmet_load_wh'],[7,13]);self.assertEqual(value['maximum_abs_current_a'],1.25)
        self.assertEqual(value['electrical_extrema_scope'],'SELECTED_START_HELD_SAMPLES_NOT_CONTINUOUS_BOUNDS')
        self.assertEqual(value['battery_capacity_retention'],dict(start=1,end=.99))
        self.assertEqual(value['PV_retention']['end'],UNKNOWN)

    def test_cumulative_ninety_day_tip_never_becomes_monthly_extrema(self):
        rows=thirty_day_summaries([dict(science=dict(report=dict(totals={'minimum_energy_wh':0})),source={'sha256':'a'*64})])
        self.assertEqual(len(rows),3);self.assertTrue(all(x['state']=='UNKNOWN'for x in rows))
        self.assertEqual(rows[-1]['requested_interval']['end_seconds'],7776128)

    def test_only_exact_source_owned_month_interval_is_reported(self):
        row=dict(start_seconds=128,end_seconds=128+30*86400,totals={'credits':3})
        source={'path':'saved-source-only','sha256':'b'*64}
        rows=thirty_day_summaries([dict(science=dict(report={'interval_summaries':[row]}),source=source)])
        self.assertEqual(rows[0]['state'],'RECORDED');self.assertEqual(rows[0]['evidence']['source'],source)
        self.assertEqual(rows[1]['state'],'UNKNOWN')
