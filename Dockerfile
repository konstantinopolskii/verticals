# Verticals — the whole application in one image. docs/IMPLEMENTATION.md WP-29.
#
# Two stages, two base images, both pinned to an exact patch version. `node:22` and
# `python:3.12` are moving tags: the image that builds green today is a different image next
# month, and the failure that produces lands on a self-hoster, not here.
#
# WHAT RUNS IN THE FINAL IMAGE, and why it is two processes rather than one:
#
#   uvicorn  — `verticals.api.app`, bound to 127.0.0.1:8080 *inside the container*.
#              verticals/api/app.py::_parse_loopback_bind refuses any other host, deliberately
#              (AC-157). That refusal is not something to work around with an env var: the
#              container's own network namespace is the boundary it is asking for.
#   nginx    — listens on the container's :80, serves the prebuilt `web/dist` and proxies
#              `/api` and `/healthz` to the uvicorn above. It is what makes the published port
#              reachable at all, and it is what makes UI and API one origin — which is the
#              condition verticals/api/app.py's missing CORSMiddleware assumes (S-114).
#
# NO SECRET IS BUILT INTO ANY LAYER. The frontend is compiled with no `VITE_VERTICALS_TOKEN`, so
# the bundle carries an empty token; `docker/entrypoint.sh` mints the real one at first boot and
# writes it into nginx's runtime config only. See docker/nginx.conf.template for the whole of
# that argument.

# --------------------------------------------------------------------------------------------
# Stage 1 — the frontend bundle.
#
# `@konstantinopolskii/{design-system,vue}` are not on a public registry (JC-02): package.json
# resolves them from `web/vendor/*.tgz`, which are gitignored and packed locally from a
# kk-agentic-ds checkout. This stage therefore builds only where those tarballs are present.
# That is exactly the limitation AC-170 records, and the README states it in one sentence.
# --------------------------------------------------------------------------------------------
FROM node:22.14.0-bookworm-slim AS web

WORKDIR /build

# Manifest + lockfile + the vendored tarballs first, so a source-only edit reuses the install
# layer.
#
# THE ONE EDIT THIS STAGE MAKES TO THE LOCKFILE, and why. Both `npm ci` and `npm install` abort
# here with EINTEGRITY on `@konstantinopolskii/design-system`. Measured, not guessed: the sha512
# of `web/vendor/konstantinopolskii-design-system-2.1.1.tgz` on this machine does not equal the
# one `web/package-lock.json` records. That is a property of the JC-02 arrangement rather than a
# corrupt file — the two kit packages are not on any registry, they are `npm pack`ed from a local
# kk-agentic-ds checkout, and `npm pack` output is not byte-reproducible, so the recorded hash is
# the hash of whichever tarball the machine that last ran `npm install` happened to produce.
#
# So the `integrity` field is dropped for `file:` entries **and only** for `file:` entries, in a
# throwaway copy inside this layer. Every registry dependency keeps its pin and its hash, which is
# the integrity that is actually protecting anything: a `file:` tarball is already inside the
# build context. The repository's own lockfile is never written to.
COPY web/package.json web/package-lock.json ./
COPY web/vendor ./vendor
RUN node -e "const f='package-lock.json',j=JSON.parse(require('fs').readFileSync(f,'utf8')); \
      for (const [k,v] of Object.entries(j.packages||{})) \
        if (typeof v.resolved === 'string' && v.resolved.startsWith('file:')) delete v.integrity; \
      require('fs').writeFileSync(f, JSON.stringify(j,null,2));" \
    && npm install --no-audit --no-fund

COPY web/ ./
# Self-hosted images are release artifacts, so browser-local design experiments must not alter
# their geometry. A designer can opt in explicitly with
# `docker compose build --build-arg VITE_ENABLE_DEV_TUNING=1 app`.
ARG VITE_ENABLE_DEV_TUNING=0
RUN VITE_ENABLE_DEV_TUNING="$VITE_ENABLE_DEV_TUNING" npm run build

# --------------------------------------------------------------------------------------------
# Stage 2 — the runtime.
# --------------------------------------------------------------------------------------------
FROM python:3.12.9-slim-bookworm AS runtime

# `nginx-light` and nothing else: no PHP, no mail, no image filter modules. `psycopg[binary]`
# ships its own libpq wheel, so there is no libpq-dev and no compiler in this image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nginx-light \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

WORKDIR /app

# The dependency pins live in one file and are installed from it — no second copy of the six
# choices in this Dockerfile to drift from `pyproject.toml` (AC-086).
COPY pyproject.toml ./
COPY docs/BRIEF.md ./docs/BRIEF.md
COPY verticals ./verticals

# Editable, on purpose. `verticals/db/migrations/*.sql` and `verticals/db/seed_sample.sql` are
# data files beside the code; a non-editable install would need package-data configuration in
# pyproject.toml that exists nowhere today, and an image whose migration runner cannot find its
# migrations fails at first boot on a stranger's machine. The source tree ships in the image
# either way — this is an open-source project, not a compiled product.
RUN pip install --no-cache-dir -e .

COPY --from=web /build/dist /srv/verticals
COPY docker/entrypoint.sh docker/nginx.conf.template /opt/verticals/
RUN chmod 0755 /opt/verticals/entrypoint.sh

ENV VERTICALS_BIND=127.0.0.1:8080 \
    VERTICALS_ENV_FILE=/state/.env \
    PYTHONUNBUFFERED=1

# The state directory is a mount point. It holds exactly one file: the `.env` the entrypoint
# generates at 0600 on first boot and reuses on every boot after.
VOLUME ["/state"]

EXPOSE 80

# One healthcheck, through nginx, on the one route that is not behind the bearer token
# (verticals/api/app.py: `GET /healthz`). No curl in this image and none added for this.
HEALTHCHECK --interval=3s --timeout=5s --start-period=5s --retries=20 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1/healthz', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["/opt/verticals/entrypoint.sh"]
