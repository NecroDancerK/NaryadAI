import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('benchmark',Path(__file__).with_name('vlm_mvp_benchmark.py'))
benchmark=importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class BenchmarkTest(unittest.TestCase):
    def report(self,prompt='one'):
        return {'model':'qwen','model_sha256':'model','mmproj_sha256':'projector','client_source_sha256':'client','manifest_sha256':'dataset','parameters':{'seed':42},'prompt_sha256':prompt,'gpu':{},'results':[{'id':1,'image_sha256':'photo','status':'ok','seconds':2,'result':{'observations':['Нет явных дефектов'],'limitations':[]}}]}

    def test_prompt_override_is_explicit_and_defaults_stay_unchanged(self):
        self.assertEqual(benchmark.experiment_prompt('default','v1'),('default','v1'))
        with self.assertRaises(ValueError):
            benchmark.experiment_prompt('default','v1',version='experiment-v2')
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'prompt.txt';path.write_text('test instructions')
            self.assertEqual(benchmark.experiment_prompt('default','v1',path,'experiment-v2'),('test instructions','experiment-v2'))
            with self.assertRaises(ValueError):
                benchmark.experiment_prompt('default','v1',path,'production-v2')

    def test_comparison_requires_the_same_images_parameters_and_client(self):
        for key in ['model_sha256','mmproj_sha256','client_source_sha256','manifest_sha256','parameters']:
            left=self.report();right=self.report('two');right[key]='changed'
            with self.assertRaisesRegex(ValueError,'more than'):
                benchmark.compare_reports(left,right)
        left=self.report();right=self.report('two');right['results'][0]['image_sha256']='other'
        with self.assertRaisesRegex(ValueError,'images'):
            benchmark.compare_reports(left,right)

    def test_word_counts_are_not_accuracy_even_when_the_phrase_is_a_negation(self):
        compared=benchmark.compare_reports(self.report(),self.report('two'))
        self.assertEqual(compared['baseline']['observation_vocabulary_cases'],1)
        self.assertIsNone(compared['quality_score'])
        self.assertIn('not hallucination',compared['warning'])

    def test_errors_are_counted_and_quality_is_not_inferred(self):
        result=benchmark.summary([{'status':'ok','seconds':2},{'status':'error','seconds':90}])
        self.assertEqual(result['samples'],2)
        self.assertEqual(result['errors'],1)
        self.assertIsNone(result['quality_score'])
        self.assertEqual(result['median_success_seconds'],2)

    def test_empty_review_is_not_100_percent_quality(self):
        report={'results':[{'id':1,'status':'ok'}]}
        review=benchmark.review_template(report);review['reviewer']='Test reviewer'
        self.assertEqual(benchmark.summarize_review(report,review)['judged_cases'],0)

    def test_review_is_bound_to_exact_answers(self):
        report={'results':[{'id':1,'status':'ok'}]}
        review=benchmark.review_template(report);report['results'][0]['result']='changed'
        with self.assertRaisesRegex(ValueError,'different report'):
            benchmark.summarize_review(report,review)

    def test_manual_grades_and_unjudgeable_cases_have_separate_denominators(self):
        report={'results':[{'id':1,'status':'ok'},{'id':2,'status':'ok'}]}
        review=benchmark.review_template(report);review['reviewer']='Test reviewer'
        review['cases'][0].update(grounding='ungrounded',hallucinated_detail=True,unsupported_safety_or_repair_claim=False,appropriate_uncertainty=False)
        review['cases'][1]['grounding']='cannot_judge'
        result=benchmark.summarize_review(report,review)
        self.assertEqual(result['judged_cases'],1)
        self.assertEqual(result['unjudged_or_cannot_judge'],1)
        self.assertEqual(result['hallucinated_detail_cases'],1)

    def test_changed_images_and_path_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);image=directory/'sample.jpg';image.write_bytes(b'test')
            manifest=directory/'manifest.json'
            sample={'file':'sample.jpg','sha256':benchmark.digest(image)}
            manifest.write_text(json.dumps({'samples':[sample]}))
            self.assertEqual(len(benchmark.samples_from(manifest)[1]),1)
            image.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'SHA256'):
                benchmark.samples_from(manifest)
            sample['file']='../outside.jpg';manifest.write_text(json.dumps({'samples':[sample]}))
            with self.assertRaisesRegex(ValueError,'inside'):
                benchmark.samples_from(manifest)

    def test_report_escapes_untrusted_model_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary);image=directory/'sample.jpg';image.write_bytes(b'\xff\xd8\xfftest')
            manifest=directory/'manifest.json';sha=benchmark.digest(image)
            manifest.write_text(json.dumps({'samples':[{'file':'sample.jpg','sha256':sha}]}))
            report={'model':'model','prompt_version':'v1','dataset':{},'summary':{},'gpu':{},'results':[{'id':1,'image_sha256':sha,'reference':{},'result':{'observations':['<script>alert(1)</script>']}}]}
            output=benchmark.render_report(report,manifest)
            self.assertNotIn('<script>',output)
            self.assertIn('&lt;script&gt;',output)


if __name__=='__main__':
    unittest.main()
