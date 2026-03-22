"""
Arbiter AI — Text-to-Speech Voice Manager
Supports pyttsx3 (offline), Coqui TTS, or console fallback.
"""

import sys


def speak(text: str, voice: str = "British_Female") -> None:
    """Convert text to speech using the best available TTS engine."""

    # Try Coqui TTS first (higher quality)
    try:
        from TTS.api import TTS
        _speak_coqui(text, voice)
        return
    except ImportError:
        pass

    # Fallback to pyttsx3 (simpler, built-in voices)
    try:
        import pyttsx3
        _speak_pyttsx3(text, voice)
        return
    except ImportError:
        pass

    # Console fallback
    print(f"[TTS:{voice}] {text}")


def _speak_pyttsx3(text: str, voice: str) -> None:
    import pyttsx3
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")
    prefer_female = "female" in voice.lower()
    for v in voices:
        name_lower = v.name.lower()
        if prefer_female and "female" in name_lower:
            engine.setProperty("voice", v.id)
            break
        elif not prefer_female and "male" in name_lower:
            engine.setProperty("voice", v.id)
            break
    engine.say(text)
    engine.runAndWait()


def _speak_coqui(text: str, voice: str) -> None:
    """Use Coqui TTS for higher quality voice synthesis."""
    import tempfile
    import simpleaudio as sa
    from TTS.api import TTS

    model_name = (
        "tts_models/en/ljspeech/glow-tts"
        if "female" in voice.lower()
        else "tts_models/en/vctk/vits"
    )
    tts = TTS(model_name=model_name, progress_bar=False, gpu=False)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tts.tts_to_file(text=text, file_path=tmp.name)
        wave_obj = sa.WaveObject.from_wave_file(tmp.name)
        play_obj = wave_obj.play()
        play_obj.wait_done()


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        speak(sys.argv[1], sys.argv[2] if len(sys.argv) >= 3 else "British_Female")
