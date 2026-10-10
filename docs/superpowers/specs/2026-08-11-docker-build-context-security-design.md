# Docker Build-Context Security Design

## Goal

Prevent repository metadata, credentials, local data, caches, and agent artifacts from
entering the container build context before the AWS validation image is built or pushed.

## Design

Add one root `.dockerignore` file. Keep the existing `Dockerfile` and its `COPY . .`
instruction unchanged.

Exclude:

- Git metadata;
- `.env` variants, local AWS configuration, private keys, and certificates;
- virtual environments, Python bytecode, test/type/lint caches, coverage, and logs;
- local databases, uploaded media, and generated build output;
- Graphify, Superpowers, skill-observation, and skill-update artifacts.

Do not exclude application source, migrations, scripts, templates, static assets,
`pyproject.toml`, or `uv.lock`.

## Verification

This is a configuration-only change, so no synthetic unit test will duplicate Docker's
ignore semantics. Before a container engine is installed, verify the reviewed pattern set
and confirm the required runtime inputs remain in the repository. After installation, the
first real worker-image build is the behavioral check.

## Boundaries

- Do not install a container engine in this change.
- Do not build or push an image.
- Do not create ECR or CloudFormation resources.
- Revisit an explicit Dockerfile allowlist only if the denylist becomes difficult to audit.
