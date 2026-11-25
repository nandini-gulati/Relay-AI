.PHONY: up down logs test clean

# Start both services in detached mode with build
up:
	docker compose up --build -d

# Stop and remove containers, networks, and orphaned volumes
down:
	docker compose down

# Follow aggregate container logs
logs:
	docker compose logs -f

# Run backend unit and integration test suite
test:
	@if [ -d "backend/.venv" ]; then \
		backend/.venv/bin/python3 -m pytest backend/tests/test_api.py -v; \
	else \
		python3 -m pytest backend/tests/test_api.py -v; \
	fi

# Clean temporary files, caches, and database test artifacts
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	rm -rf data/*.db*
