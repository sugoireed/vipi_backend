"""Riba: Vipi speech recognition (a Whisper model) run in-process.

RIBA_MODEL points at a Hugging Face Whisper directory or hub id (openai/whisper-large-v3-turbo; previously
our fp16 copy of Rogendo/asr-whisper-largev2-v7). RIBA_ADAPTER is the optional Riba LoRA (Kenyan Swahili /
Sheng), used for Swahili-side speech only. RIBA_DEVICE picks cuda / mps / cpu.
"""
import contextlib
import io
import os
import threading

import numpy as np
import soundfile as sf
import torch
from transformers import WhisperForConditionalGeneration, WhisperProcessor

SAMPLE_RATE = 16000
SILENCE_RMS = 0.004  # below this the clip is treated as silence (Whisper hallucinates text on silence)


def _device():
    wanted = os.environ.get("RIBA_DEVICE", "")
    if wanted:
        return wanted
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class RibaEngine:
    def __init__(self, model_path, device=None, adapter=None):
        """adapter: optional Riba LoRA (Kenyan Swahili / Sheng). It is applied to Swahili-side transcription only;
        English requests run the untouched base model, so tourist-side accuracy can't regress."""
        self.device = device or _device()
        self.dtype = torch.float32 if self.device == "cpu" else torch.float16
        self.processor = WhisperProcessor.from_pretrained(model_path)
        self.model = WhisperForConditionalGeneration.from_pretrained(model_path, torch_dtype=self.dtype)
        self.name = os.path.basename(model_path.rstrip("/"))
        self.adapter = None
        if adapter:
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(self.model, adapter)
            self.adapter = os.path.basename(adapter.rstrip("/"))
        self.model.to(self.device).eval()
        self._lock = threading.Lock()  # one GPU/MPS generate at a time

    @staticmethod
    def load_audio(data: bytes):
        audio, rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if rate != SAMPLE_RATE and len(audio):
            # Linear resampling is plenty for speech recognition input.
            positions = np.linspace(0, len(audio) - 1, int(len(audio) * SAMPLE_RATE / rate))
            audio = np.interp(positions, np.arange(len(audio)), audio).astype("float32")
        return audio

    def transcribe(self, data: bytes, language: str) -> str:
        """language: Whisper code, "sw" (Swahili / Sheng) or "en". Returns "" for silence."""
        audio = self.load_audio(data)
        if len(audio) < SAMPLE_RATE * 0.3 or float(np.sqrt(np.mean(audio ** 2))) < SILENCE_RMS:
            return ""
        feats = self.processor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt").input_features
        use_adapter = self.adapter is not None and language == "sw"
        with self._lock, torch.no_grad(), (contextlib.nullcontext() if use_adapter or self.adapter is None
                                           else self.model.disable_adapter()):
            ids = self.model.generate(input_features=feats.to(self.device, self.dtype), language=language,
                                      task="transcribe", max_new_tokens=220)
        return self.processor.batch_decode(ids, skip_special_tokens=True)[0].strip()
