"""Offline regressions for the packaged APT workflow. All HTTP is prohibited."""
from pathlib import Path
from fractions import Fraction
import importlib.util
import json
import subprocess
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

T=Path(__file__).resolve().parent.parent/'assets/template'
sys.path.insert(0,str(T))
import rh_core as rh
import apt_runtime as rt
import review_media as review
from apt_media_tools import resolve_tool


class FakeTransport:
    key='offline-fixture-not-a-real-key'
    def __init__(self):
        self.calls=[];self.submissions=0;self.uploads=0;self.fail_submit=False;self.query_busy=False;self.fail_download=False
    def upload(self,path):
        self.uploads+=1;self.calls.append('upload')
        return {'filename':f'fresh-{self.uploads}'}
    def submit(self,path,body):
        self.submissions+=1;self.calls.append('submit')
        if self.fail_submit:raise TimeoutError('Unknown response')
        return {'taskId':f'paid-{self.submissions}'}
    def query(self,task):
        self.calls.append('query')
        if self.query_busy:raise rh.ApiFailure('421')
        return {'status':'SUCCESS','results':[{'url':'https://example.invalid/result.mp4','outputType':'mp4'}]}
    def download(self,url,dest):
        self.calls.append('download')
        if self.fail_download:raise TimeoutError('Download interrupted')
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b'offline downloaded result')


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.now=1000
        self.ledger=rh.Ledger(self.root/'private/tasks.sqlite',clock=lambda:self.now)
        self.transport=FakeTransport();self.runner=rt.FreshAssetRunner(self.ledger,self.transport)
        self.project=self.root/'run';self.project.mkdir()
        for name in ['video.mp4','ref.png','prompt.txt']:(self.project/name).write_text('fixture',encoding='utf8')
        self.entry={'window_id':'030_A','video_path':'video.mp4','prompt_path':'prompt.txt','reference_paths':['ref.png'],
            'generation_frames':22,'generation_fps':'24','input_digest':'fixture-digest',
            'profile':{'kind':'legacy-ai-app','app_id':'2107844752011010050','resolution_selector':{
                'aspect_ratio':'16:9 (Widescreen)','megapixels':1,'aspect_node_ids':['115','214']}}}
    def tearDown(self):self.ledger.close();self.temp.cleanup()
    def submit(self,window='030_A'):
        entry={**self.entry,'window_id':window}
        return self.runner.submit_one(self.project,entry,lambda p,e:'fixture-digest')
    def test_account_cap_shared_across_runs(self):
        for index in range(3):self.assertTrue(self.ledger.reserve('default',self.root/str(index),'job','hash'))
        other=rh.Ledger(self.root/'private/tasks.sqlite',clock=lambda:self.now)
        try:self.assertIsNone(other.reserve('default',self.root/'other','new','hash'))
        finally:other.close()
    def test_accepted_task_cannot_be_resubmitted(self):
        attempt=self.submit();self.assertEqual(self.ledger.row(attempt)['task_id'],'paid-1')
        self.assertIsNone(self.submit());self.assertEqual(self.transport.submissions,1)
    def test_unknown_post_remains_reserved(self):
        self.transport.fail_submit=True;attempt=self.submit()
        self.assertEqual(self.ledger.row(attempt)['state'],'SUBMISSION_UNKNOWN')
        self.assertIsNone(self.submit());self.assertEqual(self.transport.submissions,1)
    def test_busy_query_keeps_id_waits_60(self):
        attempt=self.submit();self.now+=6;self.transport.query_busy=True;self.runner.recover(attempt)
        row=self.ledger.row(attempt);self.assertEqual(row['task_id'],'paid-1')
        self.assertEqual(row['state'],'RUNNING');self.assertGreaterEqual(row['next_poll'],self.now+60)
        self.assertEqual(self.transport.submissions,1)
    def test_busy_submit_is_not_execution_failure(self):
        attempt=self.ledger.reserve('default',self.project,'job','hash');self.runner.submission_rejected(attempt,'421')
        self.assertEqual(self.ledger.row(attempt)['state'],'DEFERRED')
        self.assertGreaterEqual(self.ledger.account('default')['cooldown'],self.now+60)
        self.assertFalse(self.ledger.db.execute('SELECT * FROM failures').fetchall())
    def test_download_recovers_original_paid_id(self):
        attempt=self.submit();self.now+=6;self.transport.fail_download=True;self.runner.recover(attempt)
        self.assertEqual(self.ledger.row(attempt)['state'],'DOWNLOAD_FAILED')
        self.now+=31;self.transport.fail_download=False;self.runner.recover(attempt)
        self.assertEqual(self.ledger.row(attempt)['state'],'DOWNLOADED');self.assertEqual(self.transport.submissions,1)
    def test_new_submission_uses_fresh_uploads(self):
        self.submit('A');self.submit('B');self.assertEqual(self.transport.uploads,4)
    def test_three_execution_failures_pause_one_input(self):
        for index in range(3):
            attempt=self.ledger.reserve('default',self.project,'job','hash')
            self.assertTrue(attempt);self.ledger.execution_failure(attempt,'805')
        self.assertIsNone(self.ledger.reserve('default',self.project,'job','hash'))
    def test_query_then_refill_then_transfer(self):
        with patch.object(rt,'P',self.project),patch.object(rt,'validate',lambda p,e:'fixture-digest'):
            attempt=self.submit('old');self.now+=6;self.transport.calls=[]
            rt.tick(self.ledger,self.runner,[{**self.entry,'window_id':'new'}])
            self.assertLess(self.transport.calls.index('query'),self.transport.calls.index('submit'))
            self.assertLess(self.transport.calls.index('submit'),self.transport.calls.index('download'))
    def test_unknown_post_stops_other_new_jobs_immediately(self):
        self.transport.fail_submit=True
        with patch.object(rt,'P',self.project),patch.object(rt,'validate',lambda p,e:'fixture-digest'):
            self.assertTrue(rt.tick(self.ledger,self.runner,[{**self.entry,'window_id':n} for n in ['A','B','C']]))
        self.assertEqual(self.transport.submissions,1)


class ReviewTests(unittest.TestCase):
    def mapping(self):
        return {'output_indices':[0,16,74],'source_indices':[0,10,20],
            'action_start_middle_end_review':'Source first lean, middle side tilt, final rise matched.'}
    def test_actual_90_clock_allows_late_motion(self):
        self.assertEqual(review.validate_map(self.mapping(),90,21),[0,16,74])
    def test_input_76_must_not_hide_actual_90_tail(self):
        value=self.mapping();value['output_indices'][-1]=89
        self.assertEqual(review.validate_map(value,90,21)[-1],89)
        with self.assertRaises(ValueError):review.validate_map(value,76,21)
    def test_cross_shot_mapping_rejected(self):
        value=self.mapping();value.update(source_cut_before=[10],output_cut_before=[20])
        with self.assertRaises(ValueError):review.validate_map(value,90,21)
    def test_backward_mapping_rejected(self):
        value=self.mapping();value['output_indices']=[0,50,20]
        with self.assertRaises(ValueError):review.validate_map(value,90,21)
class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.project=Path(self.temp.name).resolve()
        for name in ['补齐生成用','替换用参考图','提示词','接口快照']:(self.project/name).mkdir()
        from PIL import Image
        for role in '一二':Image.new('RGB',(16,16),'blue').save(self.project/f'替换用参考图/{role}号.png')
        (self.project/'补齐生成用/041 56.mp4').write_bytes(b'fixture')
        (self.project/'补齐生成用/041.txt').write_text('Measured source action',encoding='utf8')
        (self.project/'提示词/041.txt').write_text('Current identity and source actions',encoding='utf8')
        fields=[('137','image'),('139','image'),('138','value'),('321','video'),('326','value'),('115','megapixels'),('115','aspect_ratio'),('214','aspect_ratio')]
        rt.write(self.project/'接口快照/schema.json',{'data':{'nodeInfoList':[{'nodeId':n,'fieldName':f} for n,f in fields]}})
        rt.write(self.project/'runtime.json',{'reference_selection':'provided-two','production_authorized':True,
            'production_request':'User requested a new APT role swap','approved_segments':['041']})
        self.entry={'window_id':'041','video_path':'补齐生成用/041 56.mp4','prompt_path':'提示词/041.txt',
            'reference_paths':['替换用参考图/一号.png','替换用参考图/二号.png'],'generation_frames':56,'generation_fps':'24',
            'schema_path':'接口快照/schema.json','profile':{'kind':'legacy-ai-app','app_id':'2107845954833907713',
                'resolution_selector':{'aspect_ratio':'16:9 (Widescreen)','megapixels':1,'aspect_node_ids':['115','214']}}}
        self.patches=[patch.object(rt,'P',self.project),patch.object(rt.source,'app_config',lambda:{'模式':'ai','实例':'plus'})]
        for item in self.patches:item.start()
        self.seal()
    def seal(self):
        self.entry['input_digest']=rt.input_digest(self.project,self.entry)
        self.entry['semantic_review']={'status':'passed','input_digest':self.entry['input_digest'],'notes':'Actual current role/action review complete'}
    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()
    def test_current_hash_bound_contract_valid(self):self.assertEqual(rt.validate(self.project,self.entry),self.entry['input_digest'])
    def test_changed_prompt_invalidates_semantic_review(self):
        (self.project/'提示词/041.txt').write_text('changed',encoding='utf8')
        with self.assertRaises(ValueError):rt.validate(self.project,self.entry)
    def test_partial_role_041_requires_two_slots(self):
        self.entry['reference_paths']=self.entry['reference_paths'][1:]
        with self.assertRaises(ValueError):rt.validate(self.project,self.entry)
    def test_038_and_041_match_prompt_validator(self):
        spec=importlib.util.spec_from_file_location('apt_prompt_validator',T/'validate_prompts.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        for num in ['038','041']:self.assertEqual(rt.source.CAST[num],module.CAST[num]);self.assertEqual(module.CAST[num],'一二')
    def test_10_second_limit_includes_context(self):
        self.entry['generation_frames']=241;self.seal()
        with self.assertRaises(ValueError):rt.validate(self.project,self.entry)
    def test_key_inside_run_rejected(self):
        with self.assertRaises(ValueError):rt.private_path(self.project/'private/api_key.txt')
    def test_nonexact_crop_rejected(self):
        from PIL import Image
        Image.new('RGB',(8,8),'red').save(self.project/'wrong.png')
        self.entry['reference_paths'][0]='wrong.png'
        self.entry['reference_crops']={'wrong.png':{'source_path':'替换用参考图/一号.png',
            'source_sha256':rh.sha(self.project/'替换用参考图/一号.png'),'crop':[0,0,8,8]}}
        self.seal()
        with self.assertRaises(ValueError):rt.validate(self.project,self.entry)


class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name).resolve()
        cls.clip=cls.root/'actual90.mp4';cls.source=cls.root/'source21.mp4'
        ffmpeg=resolve_tool(T,'ffmpeg')
        for path,count,audio in [(cls.clip,90,True),(cls.source,21,False)]:
            command=[ffmpeg,'-nostdin','-v','error','-f','lavfi','-i','color=c=red:s=64x36:r=24']
            if audio:command+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
            command+=['-frames:v',str(count),'-c:v','libx264','-threads','1','-pix_fmt','yuv420p']
            if audio:command+=['-c:a','aac','-shortest']
            command+=['-n',str(path)]
            subprocess.run(command,check=True,capture_output=True,timeout=30)
    @classmethod
    def tearDownClass(cls):
        # Windows executable scanners may briefly retain the already-exited binary.
        for attempt in range(10):
            try:
                cls.temp.cleanup();return
            except PermissionError:
                if attempt==9:raise
                time.sleep(0.5)
    def test_full_output_evidence_includes_89_and_keeps_pending(self):
        destination=self.root/'full-evidence'
        roi=self.root/'roi.json';rt.write(roi,[{'name':'manual','box':[0,0,32,36]}])
        review.main(['--video',str(self.clip),'--out',str(destination),'--roi',str(roi),'--native-all'])
        info=rt.read(destination/'evidence.json')
        self.assertEqual(info['actual_output_clock']['frames'],90)
        self.assertTrue((destination/'output-0089-native.png').is_file())
        self.assertTrue((destination/'output-0089-manual.png').is_file())
        self.assertEqual(info['native_rois'][0]['frame_indices'],list(range(90)))
        self.assertEqual(info['output_clock_visual_review'],'pending')
        self.assertEqual(info['source_action_review'],'pending')
    def test_actual_frames_cannot_be_declared_as_input_76(self):
        entry={'video_path':self.clip.name,'generation_frames':76,'generation_fps':'24'}
        with patch.object(rt,'P',self.root),self.assertRaises(ValueError):rt.media_check(entry)
    def test_audio_missing_rejected_before_upload(self):
        entry={'video_path':self.source.name,'generation_frames':21,'generation_fps':'24'}
        with patch.object(rt,'P',self.root),self.assertRaisesRegex(ValueError,'decodable audio'):rt.media_check(entry)
    def test_complete_video_audio_preflight(self):
        entry={'video_path':self.clip.name,'generation_frames':90,'generation_fps':'24'}
        with patch.object(rt,'P',self.root):rt.media_check(entry)


if __name__=='__main__':
    with patch('urllib.request.urlopen',side_effect=AssertionError('Offline tests must not access the network')):
        unittest.main(verbosity=2)
