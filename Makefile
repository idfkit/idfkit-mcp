.PHONY: install
install: ## Install the virtual environment and install the pre-commit hooks
	@if [ ! -d .git ]; then \
		echo "❌ Error: Not a git repository. Run 'git init -b main' first (see README step 1)."; \
		exit 1; \
	fi
	@echo "🚀 Creating virtual environment using uv"
	@uv sync
	@uv run pre-commit install

.PHONY: check
check: ## Run code quality tools.
	@echo "🚀 Checking lock file consistency with 'pyproject.toml'"
	@uv lock --locked
	@echo "🚀 Linting code: Running pre-commit"
	@uv run pre-commit run -a
	@echo "🚀 Static type checking: Running pyright"
	@uv run pyright
	@echo "🚀 Checking for obsolete dependencies: Running deptry"
	@uv run deptry src

.PHONY: test
test: ## Test the code with pytest
	@echo "🚀 Testing code: Running pytest"
	@uv run python -m pytest --cov --cov-config=pyproject.toml --cov-report=xml

.PHONY: build
build: clean-build ## Build wheel file
	@echo "🚀 Creating wheel file"
	@uvx --from build pyproject-build --installer uv

.PHONY: clean-build
clean-build: ## Clean build artifacts
	@echo "🚀 Removing build artifacts"
	@uv run python -c "import shutil; import os; shutil.rmtree('dist') if os.path.exists('dist') else None"

.PHONY: publish
publish: ## Publish a release to PyPI.
	@echo "🚀 Publishing."
	@uvx twine upload --repository-url https://upload.pypi.org/legacy/ dist/*

.PHONY: build-and-publish
build-and-publish: build publish ## Build and publish.

.PHONY: docs-test
docs-test: ## Test if documentation can be built without warnings or errors
	@uv run zensical build --clean

.PHONY: docs
docs: ## Build and serve the documentation
	@uv run zensical serve --dev-addr localhost:8001

.PHONY: serve-http
serve-http: ## Run the MCP server locally in streamable-http mode on :8000
	@echo "🚀 Starting idfkit-mcp on http://127.0.0.1:8000/mcp/"
	@uv run python -m idfkit_mcp.server --transport http --port 8000

.PHONY: sync-wasm-assets
sync-wasm-assets: ## Copy EnergyPlus WASM assets from envelop into the package
	@test -d ../envelop/public/energyplus || \
		(echo "❌ ../envelop/public/energyplus not found. Build envelop first or run from the monorepo."; exit 1)
	@rm -rf src/idfkit_mcp/assets/energyplus
	@mkdir -p src/idfkit_mcp/assets
	@cp -R ../envelop/public/energyplus src/idfkit_mcp/assets/energyplus
	@echo "✔ Synced $$(du -sh src/idfkit_mcp/assets/energyplus | cut -f1) of WASM assets"

.PHONY: docker-build
docker-build: ## Build base Docker image (no EnergyPlus — bundles WASM assets)
	@test -d ../envelop/public/energyplus || \
		(echo "❌ ../envelop/public/energyplus not found. This Dockerfile expects to be built from the monorepo root."; exit 1)
	@echo "🚀 Building Docker image idfkit-mcp:latest (target runtime)"
	@cd .. && docker build --target runtime -f idfkit-mcp/Dockerfile -t idfkit-mcp:latest .

.PHONY: docker-build-sim
docker-build-sim: ## Build simulation Docker image (requires ENERGYPLUS_TARBALL_URL)
	@test -n "$(ENERGYPLUS_TARBALL_URL)" || (echo "❌ Set ENERGYPLUS_TARBALL_URL to an EnergyPlus Linux .tar.gz URL"; exit 1)
	@test -d ../envelop/public/energyplus || \
		(echo "❌ ../envelop/public/energyplus not found. Run from the monorepo root."; exit 1)
	@echo "🚀 Building Docker image idfkit-mcp:sim (target sim)"
	@cd .. && docker build \
		$(if $(DOCKER_PLATFORM),--platform $(DOCKER_PLATFORM),) \
		--target sim \
		--build-arg ENERGYPLUS_TARBALL_URL="$(ENERGYPLUS_TARBALL_URL)" \
		$(if $(ENERGYPLUS_TARBALL_SHA256),--build-arg ENERGYPLUS_TARBALL_SHA256="$(ENERGYPLUS_TARBALL_SHA256)",) \
		-f idfkit-mcp/Dockerfile \
		-t idfkit-mcp:sim .

.PHONY: docker-run
docker-run: ## Run base Docker container (maps host:8000 to container:8000)
	@echo "🚀 Running Docker container idfkit-mcp"
	@docker run --rm -it -p 8000:8000 --name idfkit-mcp idfkit-mcp:latest

.PHONY: docker-run-sim
docker-run-sim: ## Run simulation Docker container (maps host:8000 to container:8000)
	@echo "🚀 Running Docker container idfkit-mcp:sim"
	@docker run --rm -it -p 8000:8000 --name idfkit-mcp-sim idfkit-mcp:sim

.PHONY: docker-run-detached
docker-run-detached: ## Run Docker container in background (detached)
	@echo "🚀 Running Docker container idfkit-mcp (detached)"
	@docker run -d --rm -p 8000:8000 --name idfkit-mcp idfkit-mcp:latest

.PHONY: help
help:
	@uv run python -c "import re; \
	[[print(f'\033[36m{m[0]:<20}\033[0m {m[1]}') for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open(makefile).read(), re.M)] for makefile in ('$(MAKEFILE_LIST)').strip().split()]"

.DEFAULT_GOAL := help
