"""Bounded temporary arrays for faster-whisper's log-Mel features.

Same frame grid, periodic Hann window, reflect padding and GLOBAL log clamp as
faster-whisper's FeatureExtractor. Audio is not split into independent transcripts.
Only the small FFT/magnitude intermediates are tiled; waveform and output remain
linear in duration. No GPU/model imports are needed to test this adapter.
"""


class BoundedFeatureExtractor:
    def __init__(self, original, block_frames=2048):
        if not isinstance(block_frames, int) or block_frames < 1:
            raise ValueError('block_frames must be positive')
        self.original = original
        self.block_frames = block_frames

    def __getattr__(self, name):
        return getattr(self.original, name)

    def __call__(self, waveform, padding=160, chunk_length=None):
        import numpy as np
        original = self.original
        if chunk_length is not None:
            original.n_samples = chunk_length * original.sampling_rate
            original.nb_max_frames = original.n_samples // original.hop_length
        waveform = np.asarray(waveform, dtype=np.float32)
        if waveform.ndim != 1:
            raise ValueError('Expected mono audio')
        if padding:
            waveform = np.pad(waveform, (0, padding))
        waveform = np.pad(waveform, (original.n_fft // 2, original.n_fft // 2), mode='reflect')
        # The upstream algorithm discards the final STFT frame, not the last
        # frame of every block. Blocks overlap only in their input sample windows.
        frames = (waveform.size - original.n_fft) // original.hop_length
        if frames < 1:
            raise ValueError('Audio has no feature frames')
        output = np.empty((original.mel_filters.shape[0], frames), dtype=np.float32)
        window = np.hanning(original.n_fft + 1)[:-1].astype(np.float32)
        for first in range(0, frames, self.block_frames):
            count = min(self.block_frames, frames - first)
            start = first * original.hop_length
            samples = waveform[start:start + (count - 1) * original.hop_length + original.n_fft]
            spectrum = original.stft(samples, original.n_fft, original.hop_length,
                                     window=window, center=False, return_complex=True).astype(np.complex64)
            magnitudes = np.abs(spectrum)
            np.square(magnitudes, out=magnitudes)
            mel = original.mel_filters @ magnitudes
            np.maximum(mel, 1e-10, out=mel)
            np.log10(mel, out=mel)
            output[:, first:first + count] = mel
            del spectrum, magnitudes, mel
        np.maximum(output, output.max() - 8.0, out=output)
        output += 4.0
        output /= 4.0
        return output
