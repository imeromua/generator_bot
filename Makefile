.PHONY: help install dev lint format test test-cov clean docker-build docker-up docker-down check pre-commit

# Default target
.DEFAULT_GOAL := help

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install production dependencies
	pip install -r requirements.txt

dev: ## Install development dependencies
	pip install -e ".[dev]"
	pre-commit install

lint: ## Run all linters (ruff, black, isort, mypy)
	@echo "Running ruff..."
	ruff check .
	@echo "Checking black formatting..."
	black --check .
	@echo "Checking isort..."
	isort --check-only .
	@echo "Running mypy..."
	mypy .

format: ## Auto-format code with black, isort, ruff
	@echo "Formatting with black..."
	black .
	@echo "Sorting imports with isort..."
	isort .
	@echo "Auto-fixing with ruff..."
	ruff check . --fix

test: ## Run tests with pytest
	pytest -v

test-cov: ## Run tests with coverage report
	pytest --cov --cov-report=html --cov-report=term
	@echo "\nCoverage report generated in htmlcov/index.html"

test-unit: ## Run only unit tests
	pytest -v -m unit

test-integration: ## Run only integration tests
	pytest -v -m integration

clean: ## Remove cache and temporary files
	@echo "Cleaning Python cache..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@echo "Cleaning coverage reports..."
	rm -rf htmlcov/ .coverage coverage.xml 2>/dev/null || true
	@echo "Cleaning build artifacts..."
	rm -rf build/ dist/ *.egg-info 2>/dev/null || true
	@echo "Done!"

check: ## Run all checks (pre-commit + tests)
	@echo "Running pre-commit hooks..."
	pre-commit run --all-files
	@echo "\nRunning tests..."
	pytest

pre-commit: ## Run pre-commit hooks manually
	pre-commit run --all-files

docker-build: ## Build Docker image
	docker-compose build

docker-up: ## Start all services with Docker Compose
	docker-compose up -d
	@echo "Services started. View logs with: make docker-logs"

docker-down: ## Stop all Docker services
	docker-compose down

docker-logs: ## Show Docker logs
	docker-compose logs -f bot

docker-restart: ## Restart Docker services
	docker-compose restart

docker-clean: ## Remove all Docker containers and volumes
	docker-compose down -v

run: ## Run bot locally
	python main.py

run-admin: ## Run admin bot locally
	python admin_bot.py

migrate: ## Run database migrations (placeholder)
	@echo "Database auto-initializes on startup"

backup: ## Create database backup
	@mkdir -p backups
	@if [ "$(DB_BACKEND)" = "postgres" ]; then \
		echo "Creating PostgreSQL backup..."; \
		docker-compose exec postgres pg_dump -U botuser generator_bot > backups/backup_$$(date +%Y%m%d_%H%M%S).sql; \
	else \
		echo "Creating SQLite backup..."; \
		cp generator.db backups/backup_$$(date +%Y%m%d_%H%M%S).db; \
	fi
	@echo "Backup created in backups/"

security: ## Run security checks
	@echo "Running bandit security scan..."
	bandit -r . -ll || true
	@echo "\nRunning safety check..."
	safety check || true

update-deps: ## Update dependencies
	pip list --outdated
	@echo "\nTo update all: pip install -U pip setuptools wheel && pip install -U -r requirements.txt"

docs-serve: ## Serve documentation (if using MkDocs)
	@echo "Documentation available in docs/ folder"
	@echo "View README.md and docs/*.md files"

info: ## Show project information
	@echo "Project: generator_bot"
	@echo "Python: $$(python --version)"
	@echo "Location: $$(pwd)"
	@echo ""
	@echo "Key files:"
	@echo "  - main.py          (Main bot)"
	@echo "  - admin_bot.py     (Admin bot)"
	@echo "  - config.py        (Configuration)"
	@echo "  - pyproject.toml   (Project config)"
	@echo ""
	@echo "Run 'make help' to see all available commands"
