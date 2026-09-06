.PHONY: fetch build report test reviewetta help

help:
	@echo "fetch  - download Homebrew/MacPorts/Fink snapshots to data/raw/"
	@echo "build  - match everything into mappings/*.csv + data/catalog.sqlite"
	@echo "report - regenerate mappings/REPORT.md"
	@echo "test   - run guardrail tests"

fetch:
	python3 metamacpkg/fetch.py

build:
	python3 -m metamacpkg.cli build

report:
	python3 -m metamacpkg.cli report

test:
	python3 -m unittest discover -s tests
