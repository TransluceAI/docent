deployment = "prod"

create_datadog_integration = true

private_subnet_count = 2
public_subnet_count = 2
nat_gateway_count = 2

rds_instance_class = "db.m5.8xlarge"
rds_max_allocated_storage = 4000
rds_multi_az = true
elasticache_node_type = "cache.m6g.large"
# db_password = ...  # you need to set this in the environment variables

# API on ECS Fargate + ALB (replaces App Runner)
use_ecs_api = true
ecs_api_cpu = 4096
ecs_api_memory = 8192
ecs_api_min_size = 4
ecs_api_max_size = 20
ecs_api_desired_count = 4
ecs_api_num_workers = 2
api_acm_certificate_arn = "arn:aws:acm:us-east-1:010526267928:certificate/8de8fcad-1bff-4d03-8989-1fd0c489864c"

ecs_cpu = 4096
ecs_memory = 8192
ecs_min_size = 1
ecs_max_size = 8
ecs_default_workers = 4
ecs_workers_per_queue = {
  default              = 6
  telemetry_processing = 4
  telemetry_ingest     = 4
}
worker_queue_target_depths = {
  default              = 3
  telemetry_processing = 2
  telemetry_ingest     = 4
}

# Telemetry processing worker service
telemetry_processing_ecs_min_size     = 1
telemetry_processing_ecs_max_size     = 8

# Telemetry ingest worker service
telemetry_ingest_ecs_min_size     = 1
telemetry_ingest_ecs_max_size     = 8

# Queue-depth target tracking (shared by all worker services)
worker_queue_target_depth       = 1
worker_queue_scale_in_cooldown  = 60
worker_queue_scale_out_cooldown = 60

bastion_public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQDXuwJW6+9RP5NWApvp/K7dViSSYTuE30g/3BBp0Ys5rJXRebQz3KscCAYHBH9riN9XsVb2TfngbkMEiMaZeGlH6W9UeAYdou8/tpJk8jAGQxO7nhiPCKHOgA6e6wn26PX+LwiflWWi1AwVKkbVuiyDcbbTI0cIusMucZOuA1Ruv8VhjRQt89JS95kY/j1aqXbNUKdqVLkPGKfml2dVEgaM0Eqgm5ykUc06/BlM6DXL9mrHuilsU1J5E+gp++A1LIHUvMmN+zj41iAauBU6ClnR54ABmZw2k6dWHXWecfnK+lI8n5Fy/f4pLIf7UmVUda+yEHzMziUfCZXoLLinSHbXloRaxNvUCJDFo2V/CdPLJZnrRE3yWPyZ/PO8Q+hCwmO0iMVw3IQ3eQL9YeKUzGmyv0Wxw4nhRtGFpB65cxq7KvoTeWdkeOi4xvh9V/dHRXwk4XdAaiTeWk7YmbihYJ4+0T+ks5K8XTAMc1ow+7EkUkCkVCRrWjoJgBNzC3N4NHeQewXDXzbOHGahtiRTlxaLKU0kNrUQeyAtinsMCu/Bwo6PlAaMaa78cMxM76kbuzoy+2Vipo7TwOBxcH9Wfiupoy0CPcFMybxIo/ZsHQPrw12V1Cw3zTRYjWshYSVLGmN1lspQx86xNU2KS68wlTsA8sf8dMUpac36xiXZTeuZMw== docent-prod-bastion"

rds_alarm_sns_topic_arn = "arn:aws:sns:us-east-1:010526267928:RDS-CPU-Alarms"
