import os
import tempfile
from pathlib import Path

import gradio as gr
import spaces
import torch
import torchaudio as ta
from chatterbox.vc import ChatterboxVC

_MODEL = None


def _device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _model():
    global _MODEL
    if _MODEL is None:
        _MODEL = ChatterboxVC.from_pretrained(_device())
    return _MODEL


@spaces.GPU(duration=120)
def convert(source_audio: str, reference_audio: str) -> str:
    if not source_audio or not reference_audio:
        raise gr.Error("Both source audio and reference voice are required.")

    model = _model()
    wav = model.generate(
        audio=source_audio,
        target_voice_path=reference_audio,
    )

    fd, output_path = tempfile.mkstemp(prefix="lumina_chatterbox_", suffix=".wav")
    os.close(fd)
    ta.save(output_path, wav.detach().cpu(), model.sr)
    return output_path


with gr.Blocks(title="LUMINA Chatterbox Voice Conversion") as demo:
    gr.Markdown("# LUMINA Chatterbox Voice Conversion\nFree Chatterbox VC worker for LUMINA Personal Voice.")
    with gr.Row():
        source = gr.Audio(type="filepath", label="Source speech")
        reference = gr.Audio(type="filepath", label="Reference voice")
    output = gr.Audio(type="filepath", label="Converted voice")
    run = gr.Button("Convert", variant="primary")
    run.click(convert, inputs=[source, reference], outputs=output, api_name="convert")


demo.queue(default_concurrency_limit=1)
demo.launch()
