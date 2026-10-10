"""No non-live test can sign an AWS request with the developer's credentials.

tests/conftest.py::_no_real_aws_credentials points boto3 at empty credential and
config files and turns the metadata service off, so an unfaked boto3 call fails
locally instead of reaching AWS signed as whoever ran pytest.
"""

import boto3
import pytest
from botocore.exceptions import NoCredentialsError, NoRegionError


def test_boto3_finds_no_credentials() -> None:
    assert boto3.Session().get_credentials() is None


def test_an_unfaked_call_fails_before_it_is_signed() -> None:
    with pytest.raises((NoCredentialsError, NoRegionError)):
        boto3.client("sqs", region_name="eu-central-1").send_message(
            QueueUrl="https://sqs.eu-central-1.amazonaws.com/000000000000/nope", MessageBody="{}"
        )
