PACKAGEVERSION := $(shell python -c 'import tomllib; print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])')

all:

clean:
	rm -rf htmlcov
	find . -iname __pycache__ -o -iname '*.pyc' | xargs rm -rf
	rm -f .coverage
	rm -rf *.egg-info build dist

tag:
	git tag v$(PACKAGEVERSION)

publish: clean build
	twine upload dist/*

build: dist/syndicate-py-$(PACKAGEVERSION).tar.gz

dist/syndicate-py-$(PACKAGEVERSION).tar.gz:
	python3 -m build

veryclean: clean
	rm -rf .venv

PROTOCOLS_BRANCH=main
pull-protocols:
	git subtree pull -P syndicate/protocols \
		-m 'Merge latest changes from the syndicate-protocols repository' \
		git@git.syndicate-lang.org:syndicate-lang/syndicate-protocols \
		$(PROTOCOLS_BRANCH)

chat.bin: chat.prs
	preserves-schemac .:chat.prs > $@
