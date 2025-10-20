SHELL := /bin/bash
.DEFAULT_GOAL := launch

launch:
	@if [ ! -d ".venv" ]; then \
		echo "⚙️  Creating virtual environment..."; \
		uv venv; \
		uv sync --all-extras; \
	fi
	@echo "🚀 Launching Streamlit app..."
	uv run streamlit run app/app.py

lint:
	@echo "🔍 Running Ruff lint..."
	uv run ruff check src

format:
	@echo "🎨 Formatting code with Black..."
	uv run black src

sync:
	@echo "🔄 Syncing dependencies..."
	uv sync --all-extras

clean:
	@echo "🧹 Cleaning build artifacts..."
	rm -rf dist build *.egg-info __pycache__ .pytest_cache .ruff_cache
