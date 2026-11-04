data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "k3s" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.app.id]
  key_name               = var.key_name
  iam_instance_profile   = var.instance_profile
  monitoring             = true

  metadata_options {
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 2          # lets pods (CronJobs) use the instance profile
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = var.root_volume_gb
    encrypted             = true
    delete_on_termination = true
  }

  # Minimal bootstrap; everything else is Ansible's job.
  user_data = <<-EOT
    #!/bin/bash
    set -eux
    apt-get update -y
    apt-get install -y python3 python3-pip
    hostnamectl set-hostname ${var.project}-k3s
  EOT

  tags = { Name = "${var.project}-k3s" }

  lifecycle {
    ignore_changes = [ami] # don't replace the server whenever Canonical publishes a new AMI
  }
}

resource "aws_eip" "k3s" {
  domain   = "vpc"
  instance = aws_instance.k3s.id
  tags     = { Name = "${var.project}-eip" }
}
