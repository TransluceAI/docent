environment = "prod"
rds_instance_class = "db.m5.8xlarge"
elasticache_node_type = "cache.m6g.large"
# db_password = ...  # you need to set this in the environment variables

app_runner_cpu = 4096
app_runner_memory = 8192
app_runner_max_concurrency = 50
app_runner_min_size = 5
app_runner_max_size = 25

ecs_cpu = 4096
ecs_memory = 8192
worker_desired_count = 5
