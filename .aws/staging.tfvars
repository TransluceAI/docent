environment = "staging"
rds_instance_class = "db.t3.medium"
elasticache_node_type = "cache.t3.micro"
db_password = "testing-password-1301"  # FIXME(mengk): set securely

app_runner_cpu = 1024
app_runner_memory = 6144
ecs_cpu = 1024
ecs_memory = 4096
worker_desired_count = 1
