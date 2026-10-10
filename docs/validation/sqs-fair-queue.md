# SQS fair-queue validation

```json
{
  "generated_at": "2026-08-12T17:03:53.225795+00:00",
  "limits": {
    "metric_timeout_seconds": 900,
    "poll_seconds": 15
  },
  "queue": {
    "name": "tehsil-phase1-validation-ResearchQueue-LrfmdSGIZzxi"
  },
  "region": "eu-central-1",
  "schema_version": 1,
  "source_revision": "b86cc207348ef4d229b8063d9f111bff34395ed5",
  "sts": {
    "authenticated": true
  },
  "traffic": {
    "noisy_messages": 120,
    "quiet_messages": 5,
    "quiet_tenant_delay_seconds": 1,
    "quiet_tenant_threshold": 120,
    "receive_deadline_seconds": 180,
    "receive_pollers": 12
  },
  "trial_count": 3,
  "trials": [
    {
      "duration_seconds": 23.847,
      "ended_at": "2026-08-12T17:04:17.944919+00:00",
      "metrics": {
        "ApproximateAgeOfOldestMessageInQuietGroups": [
          {
            "timestamp": "2026-08-12T17:02:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ],
        "ApproximateNumberOfMessagesDelayedInQuietGroups": [
          {
            "timestamp": "2026-08-12T17:02:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ],
        "ApproximateNumberOfMessagesNotVisibleInQuietGroups": [
          {
            "timestamp": "2026-08-12T17:02:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ],
        "ApproximateNumberOfMessagesVisibleInQuietGroups": [
          {
            "timestamp": "2026-08-12T17:02:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ],
        "ApproximateNumberOfNoisyGroups": [
          {
            "timestamp": "2026-08-12T17:02:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ]
      },
      "noisy_before_first_quiet": 85,
      "passed": true,
      "received": 125,
      "started_at": "2026-08-12T17:03:54.097483+00:00"
    },
    {
      "duration_seconds": 23.816,
      "ended_at": "2026-08-12T17:04:41.760951+00:00",
      "metrics": {
        "ApproximateAgeOfOldestMessageInQuietGroups": [
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ],
        "ApproximateNumberOfMessagesDelayedInQuietGroups": [
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ],
        "ApproximateNumberOfMessagesNotVisibleInQuietGroups": [
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ],
        "ApproximateNumberOfMessagesVisibleInQuietGroups": [
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ],
        "ApproximateNumberOfNoisyGroups": [
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ]
      },
      "noisy_before_first_quiet": 83,
      "passed": true,
      "received": 125,
      "started_at": "2026-08-12T17:04:17.945169+00:00"
    },
    {
      "duration_seconds": 23.289,
      "ended_at": "2026-08-12T17:05:05.049971+00:00",
      "metrics": {
        "ApproximateAgeOfOldestMessageInQuietGroups": [
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ],
        "ApproximateNumberOfMessagesDelayedInQuietGroups": [
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ],
        "ApproximateNumberOfMessagesNotVisibleInQuietGroups": [
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ],
        "ApproximateNumberOfMessagesVisibleInQuietGroups": [
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ],
        "ApproximateNumberOfNoisyGroups": [
          {
            "timestamp": "2026-08-12T17:03:00+00:00",
            "value": 0.0
          },
          {
            "timestamp": "2026-08-12T17:04:00+00:00",
            "value": 0.0
          }
        ]
      },
      "noisy_before_first_quiet": 68,
      "passed": true,
      "received": 125,
      "started_at": "2026-08-12T17:04:41.761110+00:00"
    }
  ],
  "verdict": "passed"
}
```
