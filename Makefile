PYTHON ?= python3

.PHONY: test check

test:
	$(PYTHON) -m unittest discover -s labs/01-ollama/tests -v
	$(PYTHON) -m unittest discover -s tests -v

check: test
	$(PYTHON) labs/02-gateway/compare.py > /dev/null
	bash -n labs/01-ollama/benchmark.sh
	git diff --check
