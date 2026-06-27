import os
import asyncio
import tempfile
import queue
import time
import logging
import sys
import re
import signal
import glob
from enum import Enum
from typing import Optional, Tuple
from collections import deque
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd
import soundfile as sf
from groq import Groq
from groq import GroqError, APIConnectionError, RateLimitError, APITimeoutError
import edge_tts
import pygame
from dotenv import load_dotenv
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, before_sleep_log

from config import config

load_dotenv()

# ──────────────────────────────────────────────
#  LOGGING SETUP
# ──────────────────────────────────────────────

def setup_logging():
    """Configure logging for the application."""
    log_level = config.LOG_LEVEL.upper()
    
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(config.LOG_FILE),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()


# ──────────────────────────────────────────────
#  METRICS
# ──────────────────────────────────────────────

@dataclass
class Metrics:
    """Track application metrics."""
    total_transcriptions: int = 0
    failed_transcriptions: int = 0
    total_chat_requests: int = 0
    failed_chat_requests: int = 0
    total_tts_generations: int = 0
    failed_tts_generations: int = 0
    circuit_breaker_opens: int = 0
    start_time: float = field(default_factory=time.time)
    
    def get_uptime(self) -> float:
        return time.time() - self.start_time

metrics = Metrics()


def cleanup_temp_files():
    """Clean up temporary audio files on startup."""
    temp_patterns = ['*.mp3', '*.wav', '*.tmp']
    cleaned = 0
    
    for pattern in temp_patterns:
        for file_path in glob.glob(pattern):
            try:
                os.unlink(file_path)
                cleaned += 1
                logger.debug(f"Cleaned up temporary file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up {file_path}: {e}")
    
    if cleaned > 0:
        logger.info(f"Cleaned up {cleaned} temporary files on startup")


def health_check() -> dict:
    """Perform health check and return status."""
    health_status = {
        "status": "healthy",
        "uptime_seconds": metrics.get_uptime(),
        "metrics": {
            "transcriptions": {
                "total": metrics.total_transcriptions,
                "failed": metrics.failed_transcriptions,
                "success_rate": (
                    (metrics.total_transcriptions - metrics.failed_transcriptions) / metrics.total_transcriptions * 100
                    if metrics.total_transcriptions > 0 else 100
                )
            },
            "chat_requests": {
                "total": metrics.total_chat_requests,
                "failed": metrics.failed_chat_requests,
                "success_rate": (
                    (metrics.total_chat_requests - metrics.failed_chat_requests) / metrics.total_chat_requests * 100
                    if metrics.total_chat_requests > 0 else 100
                )
            },
            "tts_generations": {
                "total": metrics.total_tts_generations,
                "failed": metrics.failed_tts_generations,
                "success_rate": (
                    (metrics.total_tts_generations - metrics.failed_tts_generations) / metrics.total_tts_generations * 100
                    if metrics.total_tts_generations > 0 else 100
                )
            },
            "circuit_breaker_opens": metrics.circuit_breaker_opens
        },
        "circuit_breakers": {
            "transcription": {
                "state": transcription_circuit.state,
                "failure_count": transcription_circuit.failure_count
            },
            "chat": {
                "state": chat_circuit.state,
                "failure_count": chat_circuit.failure_count
            }
        },
        "api_key_configured": bool(GROQ_API_KEY)
    }
    
    # Determine overall health
    if transcription_circuit.state == "open" or chat_circuit.state == "open":
        health_status["status"] = "degraded"
    
    if not health_status["api_key_configured"]:
        health_status["status"] = "unhealthy"
    
    return health_status


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info(f"Received signal {signum}, initiating graceful shutdown")
    
    # Log final health status
    health = health_check()
    logger.info(f"Final health status: {health}")
    
    # Cleanup pygame
    try:
        pygame.mixer.quit()
        logger.info("Pygame mixer shut down")
    except Exception as e:
        logger.warning(f"Error during pygame shutdown: {e}")
    
    # Cleanup temp files
    cleanup_temp_files()
    
    logger.info("Graceful shutdown complete")
    sys.exit(0)


# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# ──────────────────────────────────────────────
#  CIRCUIT BREAKER
# ──────────────────────────────────────────────

class CircuitBreaker:
    """Simple circuit breaker to prevent cascading failures."""
    
    def __init__(self, failure_threshold: int = 5, timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "closed"  # closed, open, half-open
    
    def record_success(self):
        """Record a successful call."""
        self.failure_count = 0
        self.state = "closed"
        logger.debug("Circuit breaker: success recorded, circuit closed")
    
    def record_failure(self):
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            metrics.circuit_breaker_opens += 1
            logger.error(f"Circuit breaker: {self.failure_count} failures, circuit opened")
    
    def can_attempt(self) -> bool:
        """Check if a call should be attempted."""
        if self.state == "closed":
            return True
        
        if self.state == "open":
            # Check if timeout has elapsed
            if time.time() - self.last_failure_time >= self.timeout:
                self.state = "half-open"
                logger.info("Circuit breaker: timeout elapsed, attempting half-open")
                return True
            return False
        
        if self.state == "half-open":
            return True
        
        return False


# Global circuit breakers for different APIs
transcription_circuit = CircuitBreaker(
    failure_threshold=config.CIRCUIT_BREAKER_FAILURE_THRESHOLD, 
    timeout=config.CIRCUIT_BREAKER_TIMEOUT
)
chat_circuit = CircuitBreaker(
    failure_threshold=config.CIRCUIT_BREAKER_FAILURE_THRESHOLD, 
    timeout=config.CIRCUIT_BREAKER_TIMEOUT
)

# ──────────────────────────────────────────────
#  CONFIG VALIDATION
# ──────────────────────────────────────────────

def validate_api_key():
    """Validate that the Groq API key is present and valid."""
    api_key = config.GROQ_API_KEY
    
    if not api_key:
        logger.error("GROQ_API_KEY not found in environment variables")
        logger.error("Please set GROQ_API_KEY in your .env file")
        logger.error("Create a .env file with: GROQ_API_KEY=your_key_here")
        sys.exit(1)
    
    if not api_key.startswith("gsk_"):
        logger.warning("GROQ_API_KEY does not start with 'gsk_' - may be invalid")
    
    if len(api_key) < 20:
        logger.warning("GROQ_API_KEY seems too short - may be invalid")
    
    logger.info("API key validated successfully")
    return api_key

GROQ_API_KEY = validate_api_key()

# ──────────────────────────────────────────────
#  STATE
# ──────────────────────────────────────────────

class State(Enum):
    IDLE      = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING  = "speaking"
# ──────────────────────────────────────────────
#  SETUP
# ──────────────────────────────────────────────

client = Groq(api_key=GROQ_API_KEY)

# Separate history per language so the model never sees
# cross-language context and stays in the right language naturally.
# Use deque with maxlen to prevent unbounded growth
history: dict = {
    "en": deque(maxlen=config.MAX_HISTORY_MESSAGES),
    "hi": deque(maxlen=config.MAX_HISTORY_MESSAGES),
}

# Initialize pygame mixer with error handling
try:
    pygame.mixer.init()
    logger.info("Pygame mixer initialized successfully")
except pygame.error as e:
    logger.error(f"Failed to initialize pygame mixer: {e}")
    logger.error("Audio playback will not be available")
    sys.exit(1)


# ──────────────────────────────────────────────
#  VAD RECORDING
# ──────────────────────────────────────────────

def capture_speech(timeout: float) -> Optional[np.ndarray]:
    """
    Listens via microphone using Voice Activity Detection.

    Returns audio ndarray when:
      • Speech is detected AND then silence >= SILENCE_AFTER_SPEECH seconds.

    Returns None when:
      • No speech detected for `timeout` seconds (caller decides what to do).

    How it works:
      1. Continuously reads 100ms audio chunks into a queue.
      2. Computes RMS energy per chunk.
      3. Above ENERGY_THRESHOLD  → "speech": start/continue recording.
      4. Below threshold after speech began → silence timer starts.
      5. Silence timer expires              → user finished speaking, return audio.
      6. No speech at all for `timeout`     → return None.
    """
    audio_q   = queue.Queue()
    blocksize = int(config.SAMPLE_RATE * config.CHUNK_SECS)

    def callback(indata, frames, time_info, status):
        audio_q.put(indata.copy())

    try:
        stream = sd.InputStream(
            samplerate=config.SAMPLE_RATE,
            channels=config.CHANNELS,
            dtype="float32",
            blocksize=blocksize,
            callback=callback,
        )
        stream.start()
        logger.debug("Audio stream started successfully")
    except sd.PortAudioError as e:
        logger.error(f"Failed to initialize audio stream: {e}")
        logger.error("Please check your microphone connection and permissions")
        return None
    except Exception as e:
        logger.error(f"Unexpected error initializing audio stream: {e}")
        return None

    speech_buffer: list            = []
    pre_buffer:    list            = []   # rolling window before speech onset
    recording                      = False
    silence_start: Optional[float] = None
    idle_clock                     = time.time()

    try:
        while True:
            try:
                chunk = audio_q.get(timeout=0.5)
            except queue.Empty:
                # Check idle timeout even when mic is completely silent
                if not recording and time.time() - idle_clock >= timeout:
                    return None
                continue

            rms = float(np.sqrt(np.mean(chunk ** 2)))

            if rms >= config.ENERGY_THRESHOLD:
                # ── Speech detected ──────────────────────────────────
                idle_clock    = time.time()   # reset the no-speech clock
                silence_start = None

                if not recording:
                    recording = True
                    # Prepend pre-roll so the first syllable isn't clipped
                    speech_buffer = list(pre_buffer)

                speech_buffer.append(chunk)

            elif recording:
                # ── Silence after speech has started ─────────────────
                speech_buffer.append(chunk)   # keep trailing silence for natural cut
                if silence_start is None:
                    silence_start = time.time()
                elif time.time() - silence_start >= config.SILENCE_AFTER_SPEECH:
                    break                     # end of user's turn → exit loop

            else:
                # ── Still waiting for speech ─────────────────────────
                pre_buffer.append(chunk)
                if len(pre_buffer) > config.PRE_ROLL_CHUNKS:
                    pre_buffer.pop(0)

                if time.time() - idle_clock >= timeout:
                    return None               # timed out with no speech

    finally:
        try:
            stream.stop()
            stream.close()
            logger.debug("Audio stream closed")
        except Exception as e:
            logger.warning(f"Error closing audio stream: {e}")

    if not speech_buffer:
        return None

    audio = np.concatenate(speech_buffer, axis=0)
    return audio if len(audio) >= config.SAMPLE_RATE * config.MIN_SPEECH_SECS else None


# ──────────────────────────────────────────────
#  TRANSCRIBE
# ──────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(config.MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=config.RETRY_MIN_DELAY, max=config.RETRY_MAX_DELAY),
    retry=(
        retry_if_exception_type(APIConnectionError) |
        retry_if_exception_type(APITimeoutError) |
        retry_if_exception_type(RateLimitError)
    ),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def transcribe(audio: np.ndarray) -> Tuple[str, str]:
    """
    Returns (text, lang_code) where lang_code is 'hi' or 'en'.

    Language detection uses 3 layers in order:
      1. Whisper's detected language tag  (quick but sometimes wrong)
      2. Script scan of the transcribed text  ← THE KEY FIX
         Whisper always transcribes the correct script even when
         its language tag is wrong. Devanagari/Arabic in the text
         means Hindi, period.
      3. Default → 'en'
    
    Includes circuit breaker protection to prevent cascading failures.
    """
    if not transcription_circuit.can_attempt():
        logger.warning("Circuit breaker open: transcription blocked")
        return "", "en"
    
    metrics.total_transcriptions += 1
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name

        sf.write(tmp_path, audio, config.SAMPLE_RATE)
        logger.debug(f"Audio saved to temporary file: {tmp_path}")

        with open(tmp_path, "rb") as f:
            result = client.audio.transcriptions.create(
                model=config.STT_MODEL,
                file=f,
                response_format="verbose_json",
            )

    except APIConnectionError as e:
        logger.error(f"API connection error during transcription: {e}")
        metrics.failed_transcriptions += 1
        transcription_circuit.record_failure()
        return "", "en"
    except RateLimitError as e:
        logger.error(f"Rate limit error during transcription: {e}")
        metrics.failed_transcriptions += 1
        transcription_circuit.record_failure()
        return "", "en"
    except APITimeoutError as e:
        logger.error(f"API timeout during transcription: {e}")
        metrics.failed_transcriptions += 1
        transcription_circuit.record_failure()
        return "", "en"
    except GroqError as e:
        logger.error(f"Groq API error during transcription: {e}")
        metrics.failed_transcriptions += 1
        transcription_circuit.record_failure()
        return "", "en"
    except IOError as e:
        logger.error(f"File I/O error during transcription: {e}")
        metrics.failed_transcriptions += 1
        return "", "en"
    except Exception as e:
        logger.error(f"Unexpected error during transcription: {e}")
        metrics.failed_transcriptions += 1
        transcription_circuit.record_failure()
        return "", "en"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
                logger.debug(f"Temporary file deleted: {tmp_path}")
            except Exception as e:
                logger.warning(f"Failed to delete temporary file {tmp_path}: {e}")
        
        # Only record success if we didn't fail
        if transcription_circuit.state == "closed":
            transcription_circuit.record_success()

    text = (result.text or "").strip()
    lang = (result.language or "en").strip().lower()

    # Layer 1: normalise Whisper tag
    if lang == "ur":
        lang = "hi"
    if lang not in ("hi", "en"):
        lang = "en"

    # Layer 2: script scan — overrides the tag if script is Hindi
    for ch in text:
        cp = ord(ch)
        if 0x0900 <= cp <= 0x097F:   # Devanagari script
            lang = "hi"
            break
        if 0x0600 <= cp <= 0x06FF:   # Arabic / Urdu script
            lang = "hi"
            break

    return text, lang


# ──────────────────────────────────────────────
#  INPUT SANITIZATION
# ──────────────────────────────────────────────

def sanitize_input(text: str) -> str:
    """Sanitize user input to prevent injection attacks."""
    if not text:
        return ""
    
    # Remove null bytes
    text = text.replace('\x00', '')
    
    # Limit length to prevent DOS
    if len(text) > config.MAX_INPUT_LENGTH:
        logger.warning(f"Input truncated from {len(text)} to {config.MAX_INPUT_LENGTH} characters")
        text = text[:config.MAX_INPUT_LENGTH]
    
    # Remove excessive whitespace
    text = ' '.join(text.split())
    
    # Strip but preserve meaningful content
    text = text.strip()
    
    return text


def validate_input(text: str) -> bool:
    """Validate that input is safe to process."""
    if not text or not text.strip():
        return False
    
    # Check for suspicious patterns (basic injection detection)
    suspicious_patterns = [
        r'<script',
        r'javascript:',
        r'onerror=',
        r'onload=',
        r'eval\(',
        r'exec\(',
    ]
    
    text_lower = text.lower()
    for pattern in suspicious_patterns:
        if re.search(pattern, text_lower):
            logger.warning(f"Suspicious pattern detected in input: {pattern}")
            return False
    
    return True


def validate_response(response: str) -> bool:
    """Validate AI response is safe and appropriate."""
    if not response or not response.strip():
        logger.warning("Empty response received from AI")
        return False
    
    # Check for response length
    if len(response) > config.MAX_RESPONSE_LENGTH:
        logger.warning(f"Response too long: {len(response)} characters")
        return False
    
    # Check for suspicious patterns in response
    suspicious_patterns = [
        r'<script',
        r'javascript:',
        r'http://',
        r'https://',
    ]
    
    response_lower = response.lower()
    for pattern in suspicious_patterns:
        if re.search(pattern, response_lower):
            logger.warning(f"Suspicious pattern detected in response: {pattern}")
            return False
    
    return True


# ──────────────────────────────────────────────
#  WAKE WORD
# ──────────────────────────────────────────────

def is_wake_word(text: str) -> bool:
    lower = text.lower().strip()
    return any(w in lower for w in config.WAKE_WORDS)


# ──────────────────────────────────────────────
#  AI REPLY
# ──────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(config.MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=config.RETRY_MIN_DELAY, max=config.RETRY_MAX_DELAY),
    retry=(
        retry_if_exception_type(APIConnectionError) |
        retry_if_exception_type(APITimeoutError) |
        retry_if_exception_type(RateLimitError)
    ),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=True
)
def get_ai_reply(user_text: str, lang: str) -> str:
    """Get AI reply with circuit breaker protection."""
    if not chat_circuit.can_attempt():
        logger.warning("Circuit breaker open: chat completion blocked")
        return "I'm experiencing technical difficulties. Please try again in a moment."
    
    metrics.total_chat_requests += 1
    system       = config.SYSTEM_HI if lang == "hi" else config.SYSTEM_EN
    lang_history = history[lang]

    lang_history.append({"role": "user", "content": user_text})
    logger.debug(f"Added user message to {lang} history. History size: {len(lang_history)}")

    try:
        response = client.chat.completions.create(
            model=config.CHAT_MODEL,
            messages=[
                {"role": "system", "content": system},
                *lang_history,
            ],
            max_tokens=config.MAX_TOKENS,
            temperature=0.7,
            timeout=config.API_TIMEOUT,
        )

        if not response.choices or len(response.choices) == 0:
            logger.error("API returned no choices in response")
            return "I apologize, but I couldn't generate a response. Please try again."

        reply = response.choices[0].message.content
        if reply is None:
            logger.error("API returned None content in response")
            return "I apologize, but I couldn't generate a response. Please try again."
            
        reply = reply.strip()
        
        # Validate response
        if not validate_response(reply):
            logger.warning("Response validation failed, using fallback")
            return "I apologize, but I couldn't provide a suitable response. Please try again."
        
        lang_history.append({"role": "assistant", "content": reply})
        logger.debug(f"Added assistant response to {lang} history. History size: {len(lang_history)}")
        return reply

    except APIConnectionError as e:
        logger.error(f"API connection error during chat completion: {e}")
        metrics.failed_chat_requests += 1
        chat_circuit.record_failure()
        return "I'm having trouble connecting to the server. Please check your internet connection and try again."
    except RateLimitError as e:
        logger.error(f"Rate limit error during chat completion: {e}")
        metrics.failed_chat_requests += 1
        chat_circuit.record_failure()
        return "I'm receiving too many requests right now. Please wait a moment and try again."
    except APITimeoutError as e:
        logger.error(f"API timeout during chat completion: {e}")
        metrics.failed_chat_requests += 1
        chat_circuit.record_failure()
        return "The request took too long. Please try again."
    except GroqError as e:
        logger.error(f"Groq API error during chat completion: {e}")
        metrics.failed_chat_requests += 1
        chat_circuit.record_failure()
        return "I encountered an error processing your request. Please try again."
    except Exception as e:
        logger.error(f"Unexpected error during chat completion: {e}")
        metrics.failed_chat_requests += 1
        chat_circuit.record_failure()
        return "I encountered an unexpected error. Please try again."
    
    # Only record success if we didn't fail
    if chat_circuit.state == "closed":
        chat_circuit.record_success()


# ──────────────────────────────────────────────
#  VOICE SELECTION
# ──────────────────────────────────────────────

def pick_voice(text: str, lang: str) -> str:
    if lang == "hi":
        return config.TTS_VOICE_HI

    for ch in text:
        cp = ord(ch)
        if 0x0900 <= cp <= 0x097F:
            return config.TTS_VOICE_HI
        if 0x0600 <= cp <= 0x06FF:
            return config.TTS_VOICE_HI

    return config.TTS_VOICE_EN


# ──────────────────────────────────────────────
#  SPEAK
# ──────────────────────────────────────────────

async def _tts(text: str, path: str, voice: str):
    """Generate TTS audio with retry logic."""
    metrics.total_tts_generations += 1
    max_retries = 2
    for attempt in range(max_retries):
        try:
            await edge_tts.Communicate(text, voice=voice).save(path)
            logger.debug(f"TTS audio saved to {path}")
            return
        except Exception as e:
            logger.warning(f"TTS generation attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error(f"TTS generation failed after {max_retries} attempts: {e}")
                metrics.failed_tts_generations += 1
                raise


def speak(text: str, lang: str = "en"):
    voice = pick_voice(text, lang)
    print(f"   🔊 Voice → {voice}")
    logger.info(f"Speaking with voice: {voice}")

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name

        asyncio.run(_tts(text, tmp_path, voice))

        pygame.mixer.music.load(tmp_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(100)
        pygame.mixer.music.unload()
        logger.debug("Audio playback completed")

    except pygame.error as e:
        logger.error(f"Pygame audio playback error: {e}")
        print(f"   ⚠️ Audio playback failed: {e}")
    except Exception as e:
        logger.error(f"Error during speech synthesis: {e}")
        print(f"   ⚠️ Speech synthesis failed: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
                logger.debug(f"Temporary audio file deleted: {tmp_path}")
            except Exception as e:
                logger.warning(f"Failed to delete temporary audio file {tmp_path}: {e}")


# ──────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────

def print_banner():
    print("\n" + "=" * 56)
    print("  AcroBot 2.2 🤖  |  Aikcropolis College")
    print("=" * 56)
    print("  States:")
    print("    👂 LISTENING  — auto-detects your voice")
    print(f"    😴 IDLE       — {int(config.IDLE_TIMEOUT)}s silence → idle")
    print("                   say 'Hello' to wake up")
    print("    🔊 SPEAKING   — playing response; loops back after")
    print("  Ctrl+C to quit")
    print("=" * 56 + "\n")


def state_label(state: State) -> str:
    return {
        State.IDLE:      "😴 IDLE",
        State.LISTENING: "👂 LISTENING",
        State.SPEAKING:  "🔊 SPEAKING",
        State.PROCESSING: "🤨 PROCESSING"
    }[state]


# ──────────────────────────────────────────────
#  MAIN LOOP
# ──────────────────────────────────────────────

def main():
    logger.info("Starting AcroBot 2.2")
    
    # Cleanup temp files on startup
    cleanup_temp_files()
    
    # Log initial health status
    health = health_check()
    logger.info(f"Initial health check: {health['status']}")
    
    print_banner()

    state = State.LISTENING   # start directly in LISTENING after the greeting
    reply = ""
    lang  = "hi"

    # ── Opening greeting ──────────────────────────────────────
    try:
        speak(
            "mein AcroBot 2.2 hu, Aikcropolis College ka AI Assistant. "
            "Main aapko admission, course, department, fees, events aur "
            "college se jude sabhi jaankari देने mein madad kar sakta hoon. "
            "Kripya apna sawaal poochhiye.",
            lang="hi",
        )
    except Exception as e:
        logger.error(f"Failed to play opening greeting: {e}")
        print("   ⚠️ Could not play opening greeting")

    try:
        while True:

            # ════════════════════════════════════════════════════
            #  IDLE — wait silently for wake word
            # ════════════════════════════════════════════════════
            if state == State.IDLE:
                print(f"\n{state_label(state)}  — say 'Hello' to activate...")

                audio = capture_speech(timeout=config.IDLE_POLL_TIMEOUT)

                if audio is None:
                    # Nobody spoke for IDLE_POLL_TIMEOUT — keep idling silently
                    continue

                print("🔍 Checking for wake word...")
                wake_text, _ = transcribe(audio)
                wake_text = sanitize_input(wake_text)
                print(f"   Heard: {wake_text!r}")

                if is_wake_word(wake_text):
                    state = State.LISTENING
                    print("\n✅ Wake word detected!")
                    speak(
                        "Haan, mein sun raha hoon. Aap apna sawaal poochhiye.",
                        lang="hi",
                    )
                else:
                    print("   Not a wake word — staying idle.")

                continue

            # ════════════════════════════════════════════════════
            #  LISTENING — auto VAD; 10 s of silence → IDLE
            # ════════════════════════════════════════════════════
            if state == State.LISTENING:
                print(f"\n{state_label(state)}  "
                      f"— silence for {int(config.IDLE_TIMEOUT)}s → idle")

                audio = capture_speech(timeout=config.IDLE_TIMEOUT)

                if audio is None:
                    # 10 seconds of nothing — go idle
                    state = State.IDLE
                    print(f"\n⏱️  No speech for {int(config.IDLE_TIMEOUT)}s — going idle.")
                    speak(
                        "Mein abhi idle mode mein ja raha hoon. "
                        "Jab zaroorat ho, 'Hello' kahiye.",
                        lang="hi",
                    )
                    continue

                # ── Got speech — transcribe ────────────────────
                print("🔍 Transcribing...")
                user_text, lang = transcribe(audio)

                if not user_text:
                    print("⚠️  Could not understand — listening again.")
                    continue
                
                # Sanitize and validate input
                user_text = sanitize_input(user_text)
                if not validate_input(user_text):
                    logger.warning("Invalid input detected, skipping")
                    print("⚠️  Invalid input — listening again.")
                    continue

                print(f"   You [{lang.upper()}] › {user_text}")

                state = State.PROCESSING
                continue

            # ════════════════════════════════════════════════════
            #  SPEAKING — play reply, then return to LISTENING
            # ════════════════════════════════════════════════════
            if state == State.SPEAKING:
                print(f"\n{state_label(state)}")
                speak(reply, lang)
                state = State.LISTENING
                continue
            # ════════════════════════════════════════════════════
            # PROCESSING — STT completed, generating AI reply
            # ════════════════════════════════════════════════════
            if state == State.PROCESSING:

                print(f"\n{state_label(state)}")

                print("🤔 Thinking...")
                reply = get_ai_reply(user_text, lang)

                print(f"   AI [{lang.upper()}] › {reply}")

                state = State.SPEAKING
                continue

    except KeyboardInterrupt:
        logger.info("Shutdown requested by user")
        print("\n\n👋 Shutting down...")
        try:
            pygame.mixer.quit()
            logger.info("Pygame mixer shut down")
        except Exception as e:
            logger.warning(f"Error during pygame shutdown: {e}")
        logger.info("AcroBot 2.2 shutdown complete")


if __name__ == "__main__":
    main()