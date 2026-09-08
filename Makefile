.PHONY: test test-config test-overview test-integration check

test: test-config test-overview test-integration

test-config:
	python3 -m unittest discover -s config/tests -v

test-overview:
	$(MAKE) -C overview test-tmux

test-integration:
	python3.13 -m unittest discover -s tests -v

check:
	python3 -m compileall -q install.py config overview/overview tests
