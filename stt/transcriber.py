import os
from typing import BinaryIO, Union
from faster_whisper import WhisperModel

class SpeechToText:
    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        """
        Initialize the Faster Whisper model.
        
        Args:
            model_size: Size of the model (e.g., "tiny", "base", "small", "medium", "large-v3")
            device: Device to use ("cpu", "cuda")
            compute_type: Quantization type ("int8", "float16", "int8_float16")
        """
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_input: Union[str, BinaryIO]) -> str:
        """
        Transcribe an audio file to text.
        
        Args:
            audio_input: Path to the audio file or a binary stream.
            
        Returns:
            The transcribed text.
        """
        segments, info = self.model.transcribe(audio_input, beam_size=5)
        
        full_text = ""
        for segment in segments:
            full_text += segment.text + " "
            
        return full_text.strip()

if __name__ == "__main__":
    # Example usage:
    # transcriber = SpeechToText()
    # text = transcriber.transcribe("path/to/audio.wav")
    # print(text)
    pass
