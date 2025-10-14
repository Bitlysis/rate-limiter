lint:
	poetry run ruff check .
	poetry run mypy .

test:
	poetry run pytest tests -svvv
