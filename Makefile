.PHONY: test check

test:
	python3 -m unittest discover -s labs/01-ollama/tests -v

check: test
	bash -n labs/01-ollama/benchmark.sh
	git diff --check
