.DEFAULT_GOAL := help
SCENARIOS := normal jam overheat vibration quality-drop stopped dirty-camera dark-camera blur-camera camera-offline camera-online opcua-down opcua-up edge-ot-cut edge-ot-restore cv-ot-cut cv-ot-restore state
.PHONY: help build up down restart ps logs smoke clean validate test integration $(SCENARIOS)
help:
	@echo "Targets: build up down restart ps logs smoke validate test integration clean"
	@echo "Scenarios: $(SCENARIOS)"
	@echo "clean removes this project's volumes and all stored lab data."
build:
	docker compose build
up:
	docker compose up -d --build
down:
	docker compose down
restart:
	docker compose restart
ps:
	docker compose ps
logs:
	docker compose logs -f --tail=100
smoke:
	docker compose --profile tools run --rm tools python /tools/smoke_test.py
validate:
	docker compose config --quiet
	docker compose --profile tools run --rm -v "$(CURDIR):/workspace:ro" tools python /workspace/scripts/validate.py
test:
	docker compose --profile tools run --rm -v "$(CURDIR)/tests:/tests:ro" tools python -m unittest discover -s /tests -v
integration:
	python3 scripts/integration_test.py
clean:
	docker compose down -v
$(SCENARIOS):
	./scripts/labctl.sh $@
