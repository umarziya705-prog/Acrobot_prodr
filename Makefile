.PHONY: help install test lint format clean build docker-run docker-build deploy restart logs health

# Default target
help:
	@echo "AcroBot 2.2 - Available commands:"
	@echo ""
	@echo "  make install      - Install dependencies"
	@echo "  make test         - Run tests"
	@echo "  make lint         - Run linting"
	@echo "  make format       - Format code with black"
	@echo "  make clean        - Clean temporary files"
	@echo "  make build        - Build Docker image"
	@echo "  make docker-run   - Run with Docker Compose"
	@echo "  make docker-stop  - Stop Docker containers"
	@echo "  make deploy       - Deploy as systemd service"
	@echo "  make restart      - Restart systemd service"
	@echo "  make logs         - View application logs"
	@echo "  make health       - Check application health"
	@echo ""

# Installation
install:
	python -m venv venv
	venv/bin/pip install --upgrade pip
	venv/bin/pip install -r requirements.txt
	@echo "Installation complete. Activate with: source venv/bin/activate"

# Testing
test:
	venv/bin/python -m pytest tests/ -v --tb=short

test-coverage:
	venv/bin/python -m pytest tests/ --cov=. --cov-report=html

# Code quality
lint:
	venv/bin/flake8 main.py config.py tests/
	venv/bin/mypy config.py --ignore-missing-imports

format:
	venv/bin/black main.py config.py tests/
	venv/bin/isort main.py config.py tests/

format-check:
	venv/bin/black --check main.py config.py tests/
	venv/bin/isort --check-only main.py config.py tests/

# Cleanup
clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.tmp" -delete
	find . -type f -name "*.wav" -delete
	find . -type f -name "*.mp3" -delete
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	@echo "Cleanup complete"

# Docker
build:
	docker build -t acrobot:latest .

docker-run:
	docker-compose up -d

docker-stop:
	docker-compose down

docker-logs:
	docker-compose logs -f

# Deployment (requires sudo)
deploy:
	@echo "Deploying as systemd service..."
	@echo "This requires sudo privileges."
	sudo cp acrobot.service /etc/systemd/system/
	sudo systemctl daemon-reload
	sudo systemctl enable acrobot
	sudo systemctl start acrobot
	@echo "Deployment complete. Check status with: sudo systemctl status acrobot"

restart:
	sudo systemctl restart acrobot

stop:
	sudo systemctl stop acrobot

status:
	sudo systemctl status acrobot

# Monitoring
logs:
	sudo journalctl -u acrobot -f

app-logs:
	tail -f logs/acrobot.log

health:
	venv/bin/python -c "from main import health_check; import json; print(json.dumps(health_check(), indent=2))"

# Development
dev:
	venv/bin/python main.py

dev-debug:
	LOG_LEVEL=DEBUG venv/bin/python main.py

# Security
security:
	venv/bin/bandit -r main.py config.py

# Dependencies
deps-update:
	venv/bin/pip install --upgrade -r requirements.txt

deps-freeze:
	venv/bin/pip freeze > requirements.txt
