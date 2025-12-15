deployment = "staging"

private_subnet_count = 2
public_subnet_count = 1
nat_gateway_count = 1

rds_instance_class = "db.t3.medium"
elasticache_node_type = "cache.t3.micro"

app_runner_cpu = 2048
app_runner_memory = 4096
app_runner_max_concurrency = 100
app_runner_min_size = 1
app_runner_max_size = 10
app_runner_num_workers = 2

ecs_cpu = 2048
ecs_memory = 6144
ecs_min_size = 1
ecs_max_size = 10
ecs_default_workers = 2
ecs_workers_per_queue = {
  default              = 2
  telemetry_processing = 2
  telemetry_ingest     = 2
}
worker_queue_target_depths = {
  default              = 1
  telemetry_processing = 1
  telemetry_ingest     = 1
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

enable_frontend_app_runner = true
frontend_app_runner_cpu = 1024
frontend_app_runner_memory = 2048
frontend_app_runner_max_concurrency = 10
frontend_app_runner_min_size = 1
frontend_app_runner_max_size = 10

bastion_public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQDXuwJW6+9RP5NWApvp/K7dViSSYTuE30g/3BBp0Ys5rJXRebQz3KscCAYHBH9riN9XsVb2TfngbkMEiMaZeGlH6W9UeAYdou8/tpJk8jAGQxO7nhiPCKHOgA6e6wn26PX+LwiflWWi1AwVKkbVuiyDcbbTI0cIusMucZOuA1Ruv8VhjRQt89JS95kY/j1aqXbNUKdqVLkPGKfml2dVEgaM0Eqgm5ykUc06/BlM6DXL9mrHuilsU1J5E+gp++A1LIHUvMmN+zj41iAauBU6ClnR54ABmZw2k6dWHXWecfnK+lI8n5Fy/f4pLIf7UmVUda+yEHzMziUfCZXoLLinSHbXloRaxNvUCJDFo2V/CdPLJZnrRE3yWPyZ/PO8Q+hCwmO0iMVw3IQ3eQL9YeKUzGmyv0Wxw4nhRtGFpB65cxq7KvoTeWdkeOi4xvh9V/dHRXwk4XdAaiTeWk7YmbihYJ4+0T+ks5K8XTAMc1ow+7EkUkCkVCRrWjoJgBNzC3N4NHeQewXDXzbOHGahtiRTlxaLKU0kNrUQeyAtinsMCu/Bwo6PlAaMaa78cMxM76kbuzoy+2Vipo7TwOBxcH9Wfiupoy0CPcFMybxIo/ZsHQPrw12V1Cw3zTRYjWshYSVLGmN1lspQx86xNU2KS68wlTsA8sf8dMUpac36xiXZTeuZMw== docent-prod-bastion"
