# AcroBot 2.2 - AI Voice Assistant for Aikcropolis College

A bilingual (Hindi/English) voice-enabled AI assistant designed to help students and visitors with information about Aikcropolis College, including admissions, courses, departments, fees, and events.

## Features

- **Voice Activity Detection (VAD)** - Automatically detects when you start and stop speaking
- **Bilingual Support** - Seamlessly handles Hindi and English with automatic language detection
- **Wake Word Activation** - Say "Hello", "Hey", or "Acrobot" to activate
- **Idle Mode** - Automatically goes to sleep after 10 seconds of silence
- **Natural Conversation** - Maintains conversation context for follow-up questions
- **Production-Grade Error Handling** - Retry logic, circuit breakers, and graceful degradation
- **Comprehensive Logging** - Detailed logs for debugging and monitoring
- **Input Validation** - Sanitization and security checks for all inputs

## Prerequisites

- Python 3.10 or higher
- Microphone for voice input
- Speakers for audio output
- Groq API key (get one at https://console.groq.com/keys)
- Internet connection for API calls

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd acropolice_ai
```

### 2. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and add your Groq API key:

```
GROQ_API_KEY=your_groq_api_key_here
```

**Important:** Never commit the `.env` file to version control. It is already included in `.gitignore`.

## Usage

### Running the Application

```bash
python main.py
```

### Voice Commands

- **Wake the bot:** Say "Hello", "Hey", or "Acrobot"
- **Ask questions:** Speak naturally about college-related topics
- **Stop:** Press Ctrl+C to quit

### States

- **👂 LISTENING** - Actively listening for your voice input
- **😴 IDLE** - Waiting for wake word (after 10s of silence)
- **🤨 PROCESSING** - Transcribing and generating AI response
- **🔊 SPEAKING** - Playing the audio response

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GROQ_API_KEY` | Your Groq API key | Required |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | INFO |

### Audio Settings (in main.py)

| Setting | Description | Default |
|---------|-------------|---------|
| `SAMPLE_RATE` | Audio sample rate in Hz | 16000 |
| `ENERGY_THRESHOLD` | RMS threshold for speech detection | 0.010 |
| `SILENCE_AFTER_SPEECH` | Seconds of silence to end turn | 1.5 |
| `IDLE_TIMEOUT` | Seconds before going idle | 10.0 |
| `MAX_HISTORY_MESSAGES` | Max conversation history length | 20 |

### Voice Selection

Edit these in `main.py` to change voices:

```python
TTS_VOICE_EN = "en-US-JennyNeural"   # English voice
TTS_VOICE_HI = "hi-IN-SwaraNeural"  # Hindi voice
```

Available voices can be found in the Edge TTS documentation.

## Architecture

### Components

1. **Audio Capture** - Voice Activity Detection (VAD) using sounddevice
2. **Speech-to-Text** - Whisper Large V3 via Groq API
3. **Language Detection** - Multi-layer detection (Whisper tag + script analysis)
4. **AI Processing** - Llama 3.3 70B via Groq API
5. **Text-to-Speech** - Edge TTS for natural voice output
6. **Audio Playback** - Pygame mixer for audio output

### Error Handling

- **Retry Logic** - Automatic retries with exponential backoff for transient failures
- **Circuit Breaker** - Prevents cascading failures by blocking calls after repeated failures
- **Input Validation** - Sanitization and security checks for all user inputs
- **Response Validation** - Checks AI responses for safety and appropriateness
- **Graceful Degradation** - Provides fallback messages when services are unavailable

### Logging

Logs are written to both:
- Console (stdout)
- File (`acrobot.log`)

Log format: `timestamp - logger_name - level - message`

## Deployment

### Quick Start with Makefile

```bash
# Install dependencies
make install

# Run tests
make test

# Start application
make dev
```

### Production Deployment

For detailed deployment instructions, see [DEPLOYMENT.md](DEPLOYMENT.md).

#### Systemd Deployment (Linux)

```bash
# Deploy as systemd service
make deploy

# Check status
make status

# View logs
make logs

# Restart service
make restart
```

#### Docker Deployment

```bash
# Build Docker image
make build

# Run with Docker Compose
make docker-run

# View logs
make docker-logs

# Stop containers
make docker-stop
```

### CI/CD

The project includes a GitHub Actions CI/CD pipeline that:
- Runs tests on every push
- Performs linting and security scans
- Builds Docker images on main branch

See `.github/workflows/ci.yml` for configuration.

## Troubleshooting

### Microphone Not Working

```bash
# Check available audio devices
python -c "import sounddevice as sd; print(sd.query_devices())"
```

If no microphone is detected:
- Ensure microphone is connected
- Check system audio settings
- Verify microphone permissions

### API Errors

**"GROQ_API_KEY not found"**
- Ensure `.env` file exists
- Verify API key is set correctly
- Check that `.env` is in the project root

**"Rate limit error"**
- Wait a few moments before retrying
- Circuit breaker will automatically retry after timeout

**"API connection error"**
- Check internet connection
- Verify Groq API status
- Check firewall settings

### Audio Playback Issues

**"Failed to initialize pygame mixer"**
- Ensure audio drivers are installed
- Check system audio settings
- Verify speakers are connected

### High CPU Usage

VAD processes audio continuously. To reduce CPU usage:
- Increase `ENERGY_THRESHOLD` (e.g., to 0.025)
- Increase `CHUNK_SECS` (e.g., to 0.2)

## Security

### API Key Management

- **Never** commit `.env` to version control
- Rotate API keys regularly
- Use different keys for development and production
- Monitor API usage for anomalies

### Input Validation

All user inputs are:
- Sanitized to remove malicious content
- Length-limited to prevent DOS attacks
- Validated for suspicious patterns

### Response Validation

All AI responses are:
- Length-limited to 2000 characters
- Checked for suspicious patterns
- Blocked if unsafe content detected

## Development

### Running in Debug Mode

```bash
LOG_LEVEL=DEBUG python main.py
```

### Adding New Languages

1. Add language code to history
2. Add TTS voice selection
3. Add system prompt for the language
4. Update language detection logic

### Testing

```bash
# Run with test audio file
python main.py
```

## Production Deployment

### Pre-Deployment Checklist

- [ ] Rotate API keys (never use exposed keys)
- [ ] Set `LOG_LEVEL=INFO` or `WARNING`
- [ ] Configure monitoring and alerting
- [ ] Set up log rotation
- [ ] Configure backup for conversation history
- [ ] Test in staging environment
- [ ] Load test the system
- [ ] Set up process manager (systemd, supervisor)
- [ ] Configure firewall rules
- [ ] Set up SSL/TLS if exposing as web service

### Monitoring

Monitor these metrics:
- API error rates
- Response times
- Circuit breaker state
- Memory usage
- CPU usage
- Disk space (for logs)

### Log Rotation

Configure logrotate to manage log files:

```
/path/to/acrobot.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

## License

[Your License Here]

## Support

For issues or questions:
- Check the troubleshooting section
- Review `acrobot.log` for error details
- Contact the development team

## Acknowledgments

- Groq API for AI processing
- OpenAI Whisper for speech recognition
- Microsoft Edge TTS for voice synthesis
- Pygame for audio playback
