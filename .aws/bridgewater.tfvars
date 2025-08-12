deployment = "bwater"

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

bastion_public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAACAQDXuwJW6+9RP5NWApvp/K7dViSSYTuE30g/3BBp0Ys5rJXRebQz3KscCAYHBH9riN9XsVb2TfngbkMEiMaZeGlH6W9UeAYdou8/tpJk8jAGQxO7nhiPCKHOgA6e6wn26PX+LwiflWWi1AwVKkbVuiyDcbbTI0cIusMucZOuA1Ruv8VhjRQt89JS95kY/j1aqXbNUKdqVLkPGKfml2dVEgaM0Eqgm5ykUc06/BlM6DXL9mrHuilsU1J5E+gp++A1LIHUvMmN+zj41iAauBU6ClnR54ABmZw2k6dWHXWecfnK+lI8n5Fy/f4pLIf7UmVUda+yEHzMziUfCZXoLLinSHbXloRaxNvUCJDFo2V/CdPLJZnrRE3yWPyZ/PO8Q+hCwmO0iMVw3IQ3eQL9YeKUzGmyv0Wxw4nhRtGFpB65cxq7KvoTeWdkeOi4xvh9V/dHRXwk4XdAaiTeWk7YmbihYJ4+0T+ks5K8XTAMc1ow+7EkUkCkVCRrWjoJgBNzC3N4NHeQewXDXzbOHGahtiRTlxaLKU0kNrUQeyAtinsMCu/Bwo6PlAaMaa78cMxM76kbuzoy+2Vipo7TwOBxcH9Wfiupoy0CPcFMybxIo/ZsHQPrw12V1Cw3zTRYjWshYSVLGmN1lspQx86xNU2KS68wlTsA8sf8dMUpac36xiXZTeuZMw== docent-prod-bastion"
