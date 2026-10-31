"""Mufti fast lane (our speech-tuned Rongo): MarianMT Swahili<->English models run with CTranslate2 (int8, CPU) inside the API process.

Models are stored int8 (75 MB); compute type is picked per CPU. A converted model directory holds the CTranslate2 model plus the Marian source.spm / target.spm tokenizers
(see training/export_mufti.sh).
"""
import os
import platform

import ctranslate2
import sentencepiece as spm


class MuftiEngine:
    def __init__(self, model_dir, threads=None, compute_type=None):
        # int8 is fastest on x86 servers (AVX2); on Apple Silicon CTranslate2's int8 kernels are ~2.5x slower than
        # float32 (40 ms vs 100 ms per sentence measured on an M4 Pro), so default to float32 there.
        compute_type = compute_type or os.environ.get("MUFTI_COMPUTE_TYPE") or (
            "float32" if platform.machine() in ("arm64", "aarch64") else "int8")
        self.translator = ctranslate2.Translator(model_dir, device="cpu", compute_type=compute_type,
                                                 inter_threads=1, intra_threads=threads or os.cpu_count() or 1)
        self.source = spm.SentencePieceProcessor(model_file=os.path.join(model_dir, "source.spm"))
        self.target = spm.SentencePieceProcessor(model_file=os.path.join(model_dir, "target.spm"))

    def translate(self, text, beam_size=1):
        tokens = self.source.encode(text, out_type=str) + ["</s>"]
        result = self.translator.translate_batch([tokens], beam_size=beam_size, max_decoding_length=160)
        return self.target.decode([t for t in result[0].hypotheses[0] if t not in ("</s>", "<pad>")])
