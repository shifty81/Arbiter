import sys
import os

def speak(text: str, voice: str = "British_Female") -> None:
    """
    Text-to-Speech output placeholder.
    Replace this implementation with Coqui TTS, pyttsx3, or ElevenLabs.
    """
    try:
        import pyttsx3
        engine = pyttsx3.init()
        voices = engine.getProperty("voices")
        # Select a voice based on preference (British/American, Male/Female)
        for v in voices:
            name_lower = v.name.lower()
            if "female" in voice.lower() and "female" in name_lower:
                engine.setProperty("voice", v.id)
                break
            elif "male" in voice.lower() and "male" in name_lower:
                engine.setProperty("voice", v.id)
                break
        engine.say(text)
        engine.runAndWait()
    except ImportError:
        # Fallback: print to console if pyttsx3 not installed
        print(f"[TTS:{voice}] {text}")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        speak(sys.argv[1], sys.argv[2] if len(sys.argv) >= 3 else "British_Female")
