# set up resources defined in .aws (RDS, EC2 instance with 200GB disk each, shared subnets)
terraform init
terraform apply

# install rsync, tmux, uv, docker, docker-compose
sudo yum install rsync -y
sudo yum install nano -y
sudo yum install tmux -y
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo yum update -y
sudo yum install docker -y
sudo service docker start
sudo curl -L https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m) -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# change docker perms (requires restart afterwards)
sudo usermod -a -G docker ec2-user


# start redis
docker-compose -f docent/docker-compose-redis.yml up -d
# cd into docent
uv sync
docent server --port PORT
