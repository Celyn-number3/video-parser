"""Synthetic-only DSP regression; run with the isolated Whisper Python. No model load."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from video_parser.integrations.whisper.features import BoundedFeatureExtractor
# Load only this module, never faster_whisper.__init__, CUDA or a model.
module_path = Path(sys.prefix) / 'Lib/site-packages/faster_whisper/feature_extractor.py'
if not module_path.exists():
    module_path = Path(importlib.util.find_spec('faster_whisper').origin).with_name('feature_extractor.py')
spec = importlib.util.spec_from_file_location('upstream_features', module_path)
upstream = importlib.util.module_from_spec(spec); spec.loader.exec_module(upstream)

class FeatureTests(unittest.TestCase):
    def test_numerical_equivalence_including_global_normalization_and_boundaries(self):
        rng = np.random.default_rng(43)
        for mels in (80, 128):
            original = upstream.FeatureExtractor(feature_size=mels)
            for n in (1, 159, 160, 401, 16001, 480079):
                for padding in (160, 480):
                    for waveform in (np.zeros(n, np.float32), rng.normal(size=n).astype(np.float32)):
                        if n > 1000: waveform[:n//2] *= 1e-6
                        with self.subTest(mels=mels, samples=n, padding=padding):
                            expected = original(waveform, padding=padding)
                            actual = BoundedFeatureExtractor(original, block_frames=37)(waveform, padding=padding)
                            self.assertEqual(expected.shape, actual.shape)
                            self.assertEqual(actual.dtype, np.float32)
                            np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=2e-6)
    def test_long_synthetic_audio_bounds_every_fft_allocation(self):
        original = upstream.FeatureExtractor(feature_size=128)
        adapted = BoundedFeatureExtractor(original, block_frames=2048)
        calls = []
        stft = original.stft
        def checked(samples, n_fft, hop, **kwargs):
            frames = 1 + (samples.size - n_fft) // hop
            calls.append(frames)
            self.assertLessEqual(frames, 2048)
            self.assertFalse(kwargs['center'])
            return stft(samples, n_fft, hop, **kwargs)
        with patch.object(original, 'stft', side_effect=checked):
            output = adapted(np.zeros(16000 * 180, dtype=np.float32))
        self.assertGreater(len(calls), 1)
        self.assertEqual(output.shape, (128, 18001))
        print(json.dumps({'synthetic_seconds': 180, 'max_fft_frames': max(calls), 'blocks': len(calls), 'output_shape': list(output.shape)}))
    def test_delegate_metadata_and_float_conversion(self):
        original = upstream.FeatureExtractor()
        adapted = BoundedFeatureExtractor(original)
        signal = np.arange(900, dtype=np.float64)
        np.testing.assert_allclose(adapted(signal, padding=0, chunk_length=15), original(signal, padding=0, chunk_length=15), atol=2e-6)
        self.assertEqual(adapted.nb_max_frames, 1500)
        self.assertEqual(adapted.time_per_frame, original.time_per_frame)
        with self.assertRaises(ValueError): BoundedFeatureExtractor(original, 0)

if __name__ == '__main__': unittest.main(verbosity=2)
