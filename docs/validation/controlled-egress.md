# Controlled-egress validation

```json
{
  "fargate": {
    "checks": [
      {
        "destination_category": "public_https",
        "elapsed_seconds": 0.321,
        "error_type": null,
        "name": "public_https",
        "passed": true
      },
      {
        "destination_category": "loopback",
        "elapsed_seconds": 0.0,
        "error_type": "ConnectionRefusedError",
        "name": "blocked_loopback",
        "passed": true
      },
      {
        "destination_category": "private",
        "elapsed_seconds": 2.002,
        "error_type": "TimeoutError",
        "name": "blocked_private",
        "passed": true
      },
      {
        "destination_category": "link_local",
        "elapsed_seconds": 2.001,
        "error_type": "TimeoutError",
        "name": "blocked_link_local",
        "passed": true
      },
      {
        "destination_category": "metadata",
        "elapsed_seconds": 0.0,
        "error_type": "OSError",
        "name": "blocked_metadata",
        "passed": true
      },
      {
        "destination_category": "aws_service_endpoint",
        "elapsed_seconds": 0.051,
        "error_type": null,
        "name": "s3_endpoint",
        "passed": true
      },
      {
        "destination_category": "aws_service_endpoint",
        "elapsed_seconds": 0.045,
        "error_type": null,
        "name": "sqs_endpoint",
        "passed": true
      },
      {
        "destination_category": "aws_service_endpoint",
        "elapsed_seconds": 0.056,
        "error_type": null,
        "name": "secrets_endpoint",
        "passed": true
      }
    ],
    "exit_code": 0,
    "flow_log_match_count": 1,
    "limits": {
      "flow_log_timeout_seconds": 600,
      "poll_seconds": 5,
      "task_timeout_seconds": 180
    },
    "observation_window": {
      "ended_at": "2026-08-12T17:03:31.846096+00:00",
      "started_at": "2026-08-12T17:02:29.166091+00:00"
    },
    "passed": true,
    "public_destination_ip_count": 12
  },
  "generated_at": "2026-08-12T17:02:28.215133+00:00",
  "limits": {
    "flow_log_timeout_seconds": 600,
    "poll_seconds": 5,
    "task_timeout_seconds": 180
  },
  "region": "eu-central-1",
  "schema_version": 1,
  "source_revision": "b86cc207348ef4d229b8063d9f111bff34395ed5",
  "stack": {
    "name": "tehsil-phase1-validation"
  },
  "sts": {
    "authenticated": true
  },
  "verdict": "passed"
}
```
