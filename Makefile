.PHONY: fetch build report test webdata help

help:
	@echo "fetch  - download Homebrew/MacPorts/Fink snapshots to data/raw/"
	@echo "build  - match everything into mappings/*.csv + data/catalog.sqlite"
	@echo "report - regenerate mappings/REPORT.md"
	@echo "test   - run guardrail tests"
	@echo "webdata - export review-site data to docs/ (commit + push to update Pages)"

fetch:
	python3 metamacpkg/fetch.py

build:
	python3 -m metamacpkg.cli build

report:
	python3 -m metamacpkg.cli report

webdata:
	python3 -m metamacpkg.cli export-web

test:
	python3 -m unittest discover -s tests
