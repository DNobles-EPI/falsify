ALLURE_DIR = build/allure-results
REPORT_DIR = build/allure-report

.PHONY: test test-allure docs

test:
	poetry run python -m pytest -vv

test-allure:
	poetry run python -m pytest -rx -vv -ra --alluredir=$(ALLURE_DIR)
	allure generate --single-file $(ALLURE_DIR) -o $(REPORT_DIR)

docs:
	# python scripts/gen_diagram.py --engine dot,fdp,sfdp
	python scripts/gen_diagram.py --engine sfdp