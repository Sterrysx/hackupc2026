import asyncio
import edge_tts
import os
import tempfile
from typing import Optional

class TextToSpeech:
    def __init__(self, voice: str = "en-US-AndrewNeural"):
        """
        Initialize TTS with a specific voice.
        Some good options:
        - en-US-AndrewNeural (Male, Friendly)
        - en-US-EmmaNeural (Female, Professional)
        - en-GB-SoniaNeural (British, Clear)
        """
        self.voice = voice

    async def generate_speech(self, text: str, output_path: Optional[str] = None) -> str:
        """
        Convert text to speech and save to a file.
        
        Args:
            text: The text to speak.
            output_path: Optional path to save the .mp3 file. If None, creates a temp file.
            
        Returns:
            The path to the generated audio file.
        """
        if not output_path:
            fd, output_path = tempfile.mkstemp(suffix=".mp3")
            os.close(fd)
            
        communicate = edge_tts.Communicate(text, self.voice)
        await communicate.save(output_path)
        return output_path

# Utility function for synchronous contexts
def text_to_speech_sync(text: str, voice: str = "en-US-AndrewNeural") -> str:
    tts = TextToSpeech(voice=voice)
    return asyncio.run(tts.generate_speech(text))

if __name__ == "__main__":
    # Quick test
    path = text_to_speech_sync("Hello operator. The HP Metal Jet S100 system is nominal.")
    print(f"Audio saved to: {path}")
