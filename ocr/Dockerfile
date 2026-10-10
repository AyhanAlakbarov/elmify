# The transcript OCR program as an AWS Lambda container image (apps/documents/ocr.py invokes it).
# Its own image, never the app's: the page inventory (pdfplumber, pypdfium2) and the upload check
# (pypdf), no model, on Python 3.12 (the Lambda base image's). Build context is ocr/, so no
# app code or secret can enter it:
#   docker build --platform linux/amd64 --provenance=false -t tehsil-ocr ocr/
#
# AWS's own Python 3.12 base image: it carries the Lambda runtime client, the runtime interface
# emulator for local invokes, and boto3 (the handler's S3 read). Pinned by digest, like every base
# image here -- a tag is repointable. Bump it deliberately, together with `requires-python`
# in ocr/pyproject.toml (tests/test_bootstrap.py pins the two together).
FROM ghcr.io/astral-sh/uv:0.12.18@sha256:3adc3706091ce7c2fe595e669628caedd6d951551b92b258b7e7dbe06d9440bc AS uv

FROM public.ecr.aws/lambda/python:3.12@sha256:93ffd196f8f7698a506e7b6f442488f563adf9b45ad589bcfff57ce6b9ad4d62
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
# The exact graph ocr/uv.lock pins, hash-checked, into the task root Lambda puts on sys.path.
RUN uv export --frozen --no-dev -o /tmp/requirements.txt \
    && uv pip install --python /var/lang/bin/python3.12 --target "${LAMBDA_TASK_ROOT}" \
       --require-hashes -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt
# Lambda runs the image on a read-only file system as an unprivileged user, with /tmp the one
# writable place. HOME points anything that insists on writing
# at /tmp.
ENV HOME=/tmp
COPY read_pages.py ./
CMD ["read_pages.handler"]
