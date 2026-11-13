# Container deployment checklist (run on a machine with Docker Engine + Compose v2)

The authoring sandbox had **no Docker daemon**, so the container files (`backend/Dockerfile`, `docker-compose.yml`,
`docker/nginx.conf`) were written and YAML-validated but **not executed there**. Run the steps below and attach the
output; do not describe them as observed until you have run them.

```bash
git clone <your-repo-url> campusops && cd campusops
git checkout v1.1.1                         # deploy from the identified release
cp .env.example .env && nano .env           # set SECRET_KEY, SEED_PASSWORD, SENSOR_KEY (never commit .env)
docker compose build                        # capture: image build succeeds
docker compose up -d                        # init -> api1, api2 -> web
docker compose ps                           # capture: init exited 0; api1, api2 healthy; web up
curl -s localhost:8080/api/health           # capture: instance alternates api-1 / api-2 across calls
./scripts/smoke.sh                          # journey over the nginx entry point (optional)
docker compose restart api1                 # restart ONE instance; the other keeps serving
curl -s localhost:8080/api/health           # still 200 while api1 restarts
docker compose down                         # keep volume
docker compose up -d                        # data survives (named volume dbdata)
docker compose down -v                      # wipe volume; fresh deployment reproduces the workflow
```
Expected evidence: `docker compose ps`, health output from both instances, the audit page showing `api-1` and `api-2`,
and the same booking/ticket counts before and after `down` / `up`.
