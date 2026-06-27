"""
Configuration management for AcroBot 2.2
Centralizes all configuration settings for easy management across environments.
"""
import os
from typing import Final
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration class."""
    
    # API Configuration
    GROQ_API_KEY: Final[str] = os.getenv("GROQ_API_KEY", "")
    
    # Model Configuration
    STT_MODEL: Final[str] = "whisper-large-v3"
    CHAT_MODEL: Final[str] = "llama-3.3-70b-versatile"
    
    # TTS Voice Configuration
    TTS_VOICE_EN: Final[str] = "en-US-JennyNeural"
    TTS_VOICE_HI: Final[str] = "hi-IN-SwaraNeural"
    
    # Audio Configuration
    SAMPLE_RATE: Final[int] = 16000
    CHANNELS: Final[int] = 1
    MAX_TOKENS: Final[int] = 300
    
    # VAD Configuration
    ENERGY_THRESHOLD: Final[float] = 0.010
    SILENCE_AFTER_SPEECH: Final[float] = 1.5
    PRE_ROLL_CHUNKS: Final[int] = 6
    MIN_SPEECH_SECS: Final[float] = 0.5
    CHUNK_SECS: Final[float] = 0.1
    
    # Timeout Configuration
    IDLE_TIMEOUT: Final[float] = 10.0
    IDLE_POLL_TIMEOUT: Final[float] = 30.0
    API_TIMEOUT: Final[float] = 30.0
    
    # Memory Configuration
    MAX_HISTORY_MESSAGES: Final[int] = 20
    
    # Input Validation Configuration
    MAX_INPUT_LENGTH: Final[int] = 1000
    MAX_RESPONSE_LENGTH: Final[int] = 2000
    
    # Circuit Breaker Configuration
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: Final[int] = 5
    CIRCUIT_BREAKER_TIMEOUT: Final[float] = 60.0
    
    # Retry Configuration
    MAX_RETRIES: Final[int] = 3
    RETRY_MIN_DELAY: Final[float] = 4.0
    RETRY_MAX_DELAY: Final[float] = 10.0
    
    # Logging Configuration
    LOG_LEVEL: Final[str] = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: Final[str] = "acrobot.log"
    
    # System Prompts
    SYSTEM_EN: Final[str] = (
        "Your name is AcroBot 2.2. You are the official AI assistant of Aikcropolis College. "
        "Help students and visitors with information about admission, courses, departments, "
        "fees, events, and all college-related queries. "
        "Keep responses concise and conversational related with only Acropolis"
        "No bullet points or markdown."
    )
    
    SYSTEM_HI: Final[str] = (
        "Aapka naam AcroBot 2.2 hai. Aap Aikcropolis College ke official AI assistant hain. "
        "Students aur visitors ko admission, courses, departments, fees, events aur "
        "college se judi sabhi jaankari mein madad karein. "
        "Hamesha Roman/Latin script mein jawab dein — Devanagari (Hindi script) bilkul mat use karein. "
        "Apne uttar chhote aur batcheet ke andaz mein rakhein. "
        "Koi bullet points ya markdown nahi."
    )
    
    # Wake Words
    WAKE_WORDS: Final[list] = ["hello", "hey", "hello acrobot", "hey acrobot", "acrobot"]


class DevelopmentConfig(Config):
    """Development configuration with debug settings."""
    LOG_LEVEL: Final[str] = "DEBUG"
    ENERGY_THRESHOLD: Final[float] = 0.005  # More sensitive for testing


class ProductionConfig(Config):
    """Production configuration with optimized settings."""
    LOG_LEVEL: Final[str] = "INFO"
    MAX_HISTORY_MESSAGES: Final[int] = 10  # Reduce memory usage in production


def get_config() -> Config:
    """Get the appropriate configuration based on environment."""
    env = os.getenv("ENVIRONMENT", "development").lower()
    
    if env == "production":
        return ProductionConfig()
    return DevelopmentConfig()


# Export the active configuration
config = get_config()
