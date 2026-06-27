# Deployment Guide for AcroBot 2.2

This guide covers deploying AcroBot 2.2 to production environments.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Systemd Deployment (Linux)](#systemd-deployment-linux)
- [Docker Deployment](#docker-deployment)
- [CI/CD Pipeline](#cicd-pipeline)
- [Monitoring and Maintenance](#monitoring-and-maintenance)
- [Troubleshooting](#troubleshooting)

## Prerequisites

### System Requirements

- **OS:** Ubuntu 20.04+ or similar Linux distribution
- **Python:** 3.10 or higher
- **RAM:** Minimum 2GB, recommended 4GB
- **CPU:** 2 cores minimum
- **Storage:** 10GB free space
- **Audio:** Microphone and speakers (for local deployment)
- **Network:** Stable internet connection for API calls

### Software Requirements

- PortAudio libraries
- FFmpeg
- Python virtual environment
- systemd (for service management)

## Systemd Deployment (Linux)

### 1. Create Deployment User

```bash
# Create dedicated user
sudo useradd -m -s /bin/bash acrobot

# Add to audio group (for microphone access)
sudo usermod -a -G audio acrobot
```

### 2. Install System Dependencies

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-pip portaudio19-dev libportaudio2 libportaudiocpp0 ffmpeg
```

### 3. Deploy Application

```bash
# Create application directory
sudo mkdir -p /opt/acrobot
sudo chown acrobot:acrobot /opt/acrobot

# Copy application files
sudo cp -r . /opt/acrobot/
sudo chown -R acrobot:acrobot /opt/acrobot

# Switch to acrobot user
sudo -u acrobot -i

# Create virtual environment
cd /opt/acrobot
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 4. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your configuration
nano .env
```

Required variables:
```
GROQ_API_KEY=your_production_api_key_here
ENVIRONMENT=production
LOG_LEVEL=INFO
```

### 5. Create Directories

```bash
mkdir -p /opt/acrobot/logs
mkdir -p /opt/acrobot/temp
```

### 6. Install Systemd Service

```bash
# Copy service file
sudo cp acrobot.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable acrobot

# Start service
sudo systemctl start acrobot
```

### 7. Verify Deployment

```bash
# Check service status
sudo systemctl status acrobot

# View logs
sudo journalctl -u acrobot -f

# View application logs
tail -f /opt/acrobot/logs/acrobot.log
```

## Docker Deployment

### 1. Build Docker Image

```bash
docker build -t acrobot:latest .
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your configuration
nano .env
```

### 3. Run with Docker Compose

```bash
docker-compose up -d
```

### 4. Run with Docker (Manual)

```bash
docker run -d \
  --name acrobot \
  --restart unless-stopped \
  --env-file .env \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/temp:/app/temp \
  --device /dev/snd:/dev/snd \
  acrobot:latest
```

**Note:** Audio device access in containers is complex. For production, consider running without audio or using specialized audio forwarding solutions.

### 5. Verify Deployment

```bash
# Check container status
docker ps

# View logs
docker logs -f acrobot

# Check health
docker inspect acrobot --format='{{.State.Health.Status}}'
```

## CI/CD Pipeline

### GitHub Actions Setup

The repository includes a CI/CD pipeline (`.github/workflows/ci.yml`) that:

1. Runs tests on every push and pull request
2. Performs linting and type checking
3. Builds Docker image on main branch
4. Runs security scans

### Setting Up CI/CD

1. **Repository Secrets** (GitHub Settings → Secrets and variables → Actions):
   - `GROQ_API_KEY`: Your Groq API key for testing

2. **Enable Workflows:**
   - Push to main branch to trigger pipeline
   - Check Actions tab for pipeline status

### Manual Pipeline Trigger

```bash
# Push to trigger pipeline
git add .
git commit -m "Trigger CI/CD"
git push origin main
```

## Monitoring and Maintenance

### Log Management

#### Configure Log Rotation

Create `/etc/logrotate.d/acrobot`:

```
/opt/acrobot/logs/*.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 0640 acrobot acrobot
    sharedscripts
    postrotate
        systemctl reload acrobot > /dev/null 2>&1 || true
    endscript
}
```

#### View Logs

```bash
# Application logs
tail -f /opt/acrobot/logs/acrobot.log

# Error logs
tail -f /opt/acrobot/logs/acrobot-error.log

# Systemd logs
journalctl -u acrobot -f
```

### Health Monitoring

The application includes a health check function. Monitor:

```bash
# Check health programmatically
python -c "from main import health_check; import json; print(json.dumps(health_check(), indent=2))"
```

Key metrics to monitor:
- API success rates
- Circuit breaker states
- Response times
- Memory usage
- CPU usage

### Backup Strategy

#### Backup Configuration

```bash
# Backup configuration
tar -czf acrobot-config-backup-$(date +%Y%m%d).tar.gz /opt/acrobot/.env /opt/acrobot/config.py
```

#### Backup Logs

```bash
# Archive old logs
find /opt/acrobot/logs -name "*.log" -mtime +30 -exec gzip {} \;
```

### Updates and Upgrades

#### Update Application

```bash
# Stop service
sudo systemctl stop acrobot

# Backup current version
sudo cp -r /opt/acrobot /opt/acrobot.backup.$(date +%Y%m%d)

# Deploy new version
sudo cp -r . /opt/acrobot/
sudo chown -R acrobot:acrobot /opt/acrobot

# Update dependencies
sudo -u acrobot /opt/acrobot/venv/bin/pip install -r /opt/acrobot/requirements.txt

# Start service
sudo systemctl start acrobot

# Verify
sudo systemctl status acrobot
```

#### Rollback

```bash
# Stop service
sudo systemctl stop acrobot

# Restore backup
sudo rm -rf /opt/acrobot
sudo mv /opt/acrobot.backup.YYYYMMDD /opt/acrobot

# Start service
sudo systemctl start acrobot
```

## Troubleshooting

### Service Won't Start

```bash
# Check status
sudo systemctl status acrobot

# View detailed logs
sudo journalctl -u acrobot -n 50 --no-pager

# Check for permission issues
sudo -u acrobot python /opt/acrobot/main.py
```

### Audio Issues

```bash
# Check audio devices
python -c "import sounddevice as sd; print(sd.query_devices())"

# Check audio group membership
groups acrobot

# Add user to audio group if needed
sudo usermod -a -G audio acrobot
```

### API Errors

```bash
# Check API key
cat /opt/acrobot/.env | grep GROQ_API_KEY

# Test API connectivity
python -c "from groq import Groq; client = Groq(api_key='YOUR_KEY'); print('Connected')"

# Check circuit breaker state
python -c "from main import health_check; print(health_check()['circuit_breakers'])"
```

### High Memory Usage

```bash
# Check memory usage
ps aux | grep python

# Reduce history limit in config.py
# Edit MAX_HISTORY_MESSAGES

# Restart service
sudo systemctl restart acrobot
```

### Network Issues

```bash
# Check internet connectivity
ping api.groq.com

# Check DNS
nslookup api.groq.com

# Check firewall
sudo ufw status
```

## Security Checklist

Before deploying to production:

- [ ] API key rotated and not exposed
- [ ] `.env` file not in version control
- [ ] Firewall rules configured
- [ ] SSL/TLS enabled (if web interface)
- [ ] Regular backups configured
- [ ] Log rotation configured
- [ ] Monitoring and alerting set up
- [ ] Security scan passed
- [ ] Dependencies up to date
- [ ] User permissions minimized
- [ ] Audit logging enabled

## Performance Tuning

### Optimize for High Load

Edit `config.py`:

```python
# Reduce memory usage
MAX_HISTORY_MESSAGES = 5

# Increase timeouts
API_TIMEOUT = 45.0

# Adjust circuit breaker
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 3
CIRCUIT_BREAKER_TIMEOUT = 120.0
```

### Optimize for Low Latency

```python
# Reduce timeouts
API_TIMEOUT = 15.0

# Reduce retry delay
RETRY_MIN_DELAY = 2.0
RETRY_MAX_DELAY = 5.0
```

## Support

For deployment issues:
1. Check logs in `/opt/acrobot/logs/`
2. Review this troubleshooting guide
3. Check the main README.md
4. Contact the development team
