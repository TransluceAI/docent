deployment = "metr"

private_subnet_count = 2
public_subnet_count = 1
nat_gateway_count = 1


rds_instance_class = "db.m5.8xlarge"
elasticache_node_type = "cache.m6g.large"
# db_password = ...  # you need to set this in the environment variables

app_runner_cpu = 4096
app_runner_memory = 8192
app_runner_max_concurrency = 50
app_runner_min_size = 1
app_runner_max_size = 10
app_runner_num_workers = 4

ecs_cpu = 4096
ecs_memory = 8192
ecs_min_size = 1
ecs_max_size = 10
ecs_desired_count = 1
ecs_num_workers = 4

# Tailscale configuration (generate auth key from Tailscale admin console)
# tailscale_auth_key = "tskey-auth-..."  # Set this via environment variable or uncomment and add your key

# Frontend App Runner configuration (enabled for METR deployment)
enable_frontend_app_runner = true
frontend_app_runner_cpu = 1024
frontend_app_runner_memory = 2048
frontend_app_runner_max_concurrency = 50
frontend_app_runner_min_size = 2
frontend_app_runner_max_size = 10
