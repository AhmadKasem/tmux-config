.PHONY: test test-tmux check

test:
	python3.13 -m unittest discover -s tests -v

test-tmux:
	OVERVIEW_TEST_TMUX=1 python3.13 -m unittest discover -s tests -v

check:
	python3.13 -m compileall -q overview tests
