# Use bash for shell commands
SHELL := /bin/bash

# Default target
.DEFAULT_GOAL := launch

# Launch the Streamlit app
launch:
	@echo "🚀 Launching Streamlit app..."
	uv run streamlit run app.py

# Lint the code with Ruff
lint:
	@echo "🔍 Running Ruff lint..."
	uv run ruff check src app.py pages/

# Autoformat with Black
format:
	@echo "🎨 Formatting code with Black..."
	uv run black src app.py pages/

# Rebuild the environment
sync:
	@echo "🔄 Syncing dependencies with uv..."
	uv sync --all-extras

# Export direct dependencies to requirements.txt (for Streamlit Cloud)
requirements:
	@echo "📦 Exporting requirements.txt from pyproject.toml..."
	uv export --no-dev --no-hashes --no-emit-project > requirements.txt
	@echo "✅ requirements.txt updated"

# Clean build artifacts
clean:
	@echo "🧹 Cleaning up build artifacts..."
	rm -rf dist build src/*.egg-info **/__pycache__ .pytest_cache .ruff_cache
	@echo "✨ Clean!"

# Show project status
status:
	@echo "📊 Git status..."
	git status --short
	@echo ""
	@echo "🐍 Python environment..."
	uv run python --version
	@echo ""
	@echo "📦 Installed packages..."
	uv pip list
