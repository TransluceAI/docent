environment = "staging"
rds_instance_class = "db.t3.medium"
elasticache_node_type = "cache.t3.micro"
db_password = "testing-password-1301"  # FIXME(mengk): set securely

app_runner_cpu = 2048
app_runner_memory = 4096

app_runner_max_concurrency = 100
app_runner_min_size = 1
app_runner_max_size = 10

ecs_cpu = 2048
ecs_memory = 6144
worker_desired_count = 1
