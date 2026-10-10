# Tehsil Agent System Design Resources

## Knowledge

- [Design doc: "Runtime and boundary decisions" - local repo](docs/architecture/0001-runtime-and-boundaries.md)
  Use for: the project's own architectural decisions. Exact pointer: whole document. Why it matters: it explains why Django, PostgreSQL, SQS, private Fargate tasks, and controlled egress were chosen.
- [Reference: "Docker overview" - Docker Docs](https://docs.docker.com/get-started/docker-overview/)
  Use for: image, container, and registry concepts. Exact pointer: "Docker objects". Why it matters: the repo has a multi-stage Dockerfile with separate web and worker targets.
- [Reference: "Dockerfile overview" - Docker Docs](https://docs.docker.com/build/concepts/dockerfile/)
  Use for: how a Dockerfile becomes an image. Exact pointer: "Dockerfile". Why it matters: this project uses Dockerfile stages as runtime boundaries.
- [Framework: "The pillars of the framework" - AWS Well-Architected](https://docs.aws.amazon.com/wellarchitected/latest/framework/the-pillars-of-the-framework.html)
  Use for: system-design review vocabulary. Exact pointer: six pillars list. Why it matters: it gives simple questions for security, reliability, cost, and operations.
- [Guide: "Amazon ECS task networking options for Fargate" - AWS Docs](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html)
  Use for: why a Fargate task gets its own network interface. Exact pointer: "Fargate task networking". Why it matters: the AWS template places probe tasks in private subnets.
- [Guide: "Connect Amazon ECS applications to the internet" - AWS Docs](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/networking-outbound.html)
  Use for: public subnet vs private subnet plus NAT. Exact pointer: Fargate outbound networking options. Why it matters: this project validates controlled NAT egress.
- [Guide: "Amazon SQS fair queues" - AWS Docs](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-fair-queues.html)
  Use for: tenant fairness in shared queues. Exact pointer: MessageGroupId note for standard queues. Why it matters: `enqueue_research()` sends tenant ID as `MessageGroupId`.
- [Guide: "Using the message group ID" - AWS Docs](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/using-messagegroupid-property.html)
  Use for: FIFO ordering vs standard fair-queue behavior. Exact pointer: opening explanation. Why it matters: this repo wants fair scheduling, not strict per-tenant FIFO semantics.
- [How-to: "How to manage static files" - Django 5.2 docs](https://docs.djangoproject.com/en/5.2/howto/static-files/)
  Use for: `STATIC_URL`, `STATIC_ROOT`, and static deployment shape. Exact pointer: "Configuring static files". Why it matters: this app uses WhiteNoise and collected static files.
- [Topic: "Middleware" - Django 5.2 docs](https://docs.djangoproject.com/en/5.2/topics/http/middleware/)
  Use for: request boundary ordering. Exact pointer: middleware overview. Why it matters: tenant resolution is middleware in this project.

## Wisdom (Communities)

- [AWS re:Post](https://repost.aws/)
  Use for: AWS service behavior questions after checking primary docs.
- [Docker Community Forums](https://forums.docker.com/)
  Use for: container/runtime troubleshooting when local behavior differs from the docs.

## Gaps

- No project-specific production runbook exists yet for the web and worker services.
- No beginner glossary existed before this teaching workspace.
