.DEFAULT_GOAL := help
SCENARIOS := normal object-mix person-zone fallen-object crowded-line jam overheat vibration quality-drop stopped dirty-camera dark-camera blur-camera camera-offline camera-online opcua-down opcua-up edge-ot-cut edge-ot-restore cv-ot-cut cv-ot-restore state
.PHONY: help build up down restart ps logs smoke clean validate test integration incident-test incident-db-test yolo-test $(SCENARIOS)
help:
	@echo "Targets: build up down restart ps logs smoke validate test integration incident-test incident-db-test yolo-test clean"
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
yolo-test:
	docker compose exec cv-detector python /tools/yolo_test.py
incident-test:
	python3 scripts/incident_integration_test.py
incident-db-test:
	docker compose --profile tools run --rm --no-deps -e INCIDENT_TEST_POSTGRES=true -v "$(CURDIR)/tests:/tests:ro" tools python -m unittest discover -s /tests -p test_incidents.py -v
integration:
	python3 scripts/integration_test.py
clean:
	docker compose down -v
$(SCENARIOS):
	./scripts/labctl.sh $@
