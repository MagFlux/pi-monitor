OUTPUT_DIR = output
PORT = 8080

.PHONY: serve clean test test-unit test-integration lint help

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  serve            Serve the live dashboard at http://localhost:$(PORT) (in-memory, auto-regenerates)"
	@echo "  clean            Remove the $(OUTPUT_DIR)/ output directory"
	@echo "  test             Run all tests (unit + integration)"
	@echo "  test-unit        Run unit tests only"
	@echo "  test-integration Run integration tests only"
	@echo "  lint             Run ruff linter"
	@echo "  help             Show this help message"

serve:
	python3 pi_monitor.py --serve --port $(PORT)

clean:
	rm -rf $(OUTPUT_DIR)

test:
	python3 -m pytest tests/ -v

test-unit:
	python3 -m pytest tests/test_unit.py -v

test-integration:
	python3 -m pytest tests/test_integration.py -v

lint:
	ruff check pi_monitor.py tests/
