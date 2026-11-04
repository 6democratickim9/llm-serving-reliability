PYTHON ?= python3

.PHONY: test check

test:
	$(PYTHON) -m unittest discover -s labs/01-ollama/tests -v
	$(PYTHON) -m unittest discover -s tests -v

check: test
	bash -n labs/01-ollama/benchmark.sh
	git diff --check