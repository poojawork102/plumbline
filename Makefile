.PHONY: install run test frontend-install frontend-dev frontend-test frontend-build

install:
	pip install -r backend/requirements-dev.txt

run:
	cd backend && python app.py

test:
	cd backend && python -m pytest -q

frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-test:
	cd frontend && npm test

frontend-build:
	cd frontend && npm run build
