"""Offline provider integration: actual encoded motion + simulated remote receipts."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from PIL import Image
import channels
import rh_core as core


class ProviderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        for name, color in [('a','red'),('b','blue')]:
            Image.new('RGB',(16,16),color).save(self.root/(name+'.png'))
        (self.root/'prompt.txt').write_text('Two distinct characters',encoding='utf8')
        self.ledger = core.Ledger(self.root/'offline.sqlite')
        self.addCleanup(self.ledger.close)

    def motion(self, fps):
        subprocess.run([channels.tool(self.root,'ffmpeg'),'-v','error','-f','lavfi','-i',
            'testsrc2=s=64x64:r='+fps,'-frames:v','39','-threads','1','-c:v','libx264',
            str(self.root/'source.mp4')],check=True)

    def exercise(self, name, fps, unknown=False):
        self.motion(fps)
        channels.configure(self.root,name)
        profile = channels.profile(name)
        entry = dict(window_id='demo',reference_paths=['b.png','a.png'],prompt_path='prompt.txt',
                     video_path='source.mp4',generation_fps=fps,generation_frames=39,profile=profile)
        transport = Mock(provider=name,key='offline-fixture')
        transport.estimate.return_value = {'data':{'estimated_cost':1}}
        transport.inspect_route.return_value = {'quote_amount':1}
        expected = 56 if name=='zhenzhen' else 42
        def upload(path):
            if path.suffix=='.mp4':
                self.assertEqual(channels.probe(self.root,path)[:2],(expected,24))
                output = subprocess.check_output([channels.tool(self.root,'ffmpeg'),'-v','error','-i',str(path),
                    '-f','rawvideo','-pix_fmt','gray','-'])
                import statistics
                frames = [output[i:i+4096] for i in range(0,len(output),4096)]
                self.assertGreater(len(set(frames[:39])),12)
                self.assertLess(statistics.mean(abs(x-y) for x,y in zip(frames[38],frames[-1])),2)
            return {'url':'https://example.invalid/'+path.name,'asset_uri':'asset://'+path.name}
        transport.upload.side_effect = upload
        runner = channels.AlternateRunner(self.ledger,transport,channels.account_for(name))
        def submit(route,body):
            pending = self.ledger.db.execute("SELECT request FROM attempts WHERE state='SUBMITTING'").fetchone()
            self.assertEqual(json.loads(pending[0])['body'],body)
            if name=='chenyu':
                self.assertEqual([body['inputs'][n] for n in ('node_386_image','node_387_image')],['asset://b.png','asset://a.png'])
                self.assertEqual(body['inputs']['node_326_value'],expected)
                self.assertFalse(body['accept_external_cost_risk'])
            else:
                self.assertEqual(body['images'],['https://example.invalid/b.png','https://example.invalid/a.png'])
                self.assertEqual(body['metadata']['frames'],expected)
            if unknown:
                raise TimeoutError()
            return {'taskId':'ticket'}
        transport.submit.side_effect = submit
        aid = runner.submit_one(self.root,entry,lambda *_:'digest')
        self.assertIsNone(runner.submit_one(self.root,entry,lambda *_:'digest'))
        self.assertEqual(transport.submit.call_count,1)
        if unknown:
            old_body = transport.submit.call_args.args[1]
            self.assertEqual(self.ledger.row(aid)['state'],'SUBMISSION_UNKNOWN')
            transport.submit.side_effect = None
            transport.submit.return_value = {'taskId':'ticket'}
            runner.reconcile(self.root,aid,None)
            self.assertEqual(old_body,transport.submit.call_args.args[1])
        self.ledger.update(aid,next_poll=0)
        transport.query.return_value={'status':'SUCCESS','results':[{'outputType':'mp4','url':'https://example.invalid/video.mp4'}]}
        def download(url,path):
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(b'offline sample')
        transport.download.side_effect=download
        runner.recover(aid)
        self.assertEqual(self.ledger.row(aid)['state'],'DOWNLOADED')
        if name=='chenyu':
            transport.query.assert_called_with('ticket',channels.REVISION)
        else:
            transport.query.assert_called_with('ticket')
        self.assertEqual(channels.probe(self.root,self.root/'source.mp4')[:2],(39,channels.Fraction(fps)))

    def test_zhenzhen_23976_motion_and_order(self):
        self.exercise('zhenzhen','24000/1001')

    def test_chenyu_24_motion_and_idempotent_recovery(self):
        self.exercise('chenyu','24',unknown=True)

    def test_unselected_legacy_and_frozen_selection(self):
        self.assertEqual(channels.selected(self.root),'rh')
        with self.assertRaises(ValueError):
            channels.configure(self.root,'chenyu',self.root/'private.key')
        channels.configure(self.root,'zhenzhen')
        channels.configure(self.root,'zhenzhen')
        with self.assertRaises(ValueError):
            channels.configure(self.root,'chenyu')

    def test_reject_provider_mismatch_duplicate_slots_and_overlong_input(self):
        channels.configure(self.root,'chenyu')
        entry=dict(profile=channels.profile('zhenzhen'),generation_frames=39,generation_fps=24)
        with self.assertRaises(ValueError):channels.wire_frames(self.root,entry,['b'])
        entry['profile']=channels.profile('chenyu')
        with self.assertRaises(ValueError):channels.wire_frames(self.root,entry,['b','b'])
        self.assertEqual(channels.wire_frames(self.root,entry,['b']),42)
        entry['generation_frames']=241
        with self.assertRaises(ValueError):channels.wire_frames(self.root,entry,['a'])


if __name__=='__main__':
    unittest.main(verbosity=2)
