# AWS infrastructure

Planned resources: VPC, private ECS/Fargate services for API and workers, public load balancer, RDS PostgreSQL, S3 buckets for originals/artifacts, SQS queues, Secrets Manager, CloudWatch logs, IAM roles, and optionally Cognito. Keep environment-specific values under `environments/` and reusable resources under `modules/`.

No Terraform resources are declared yet, so `terraform apply` cannot alter AWS.
