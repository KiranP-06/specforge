output "public_ip" {
  description = "Elastic IP of the k3s node — open http://<ip>/ in a browser"
  value       = aws_eip.k3s.public_ip
}

output "instance_id" {
  value = aws_instance.k3s.id
}

output "s3_bucket" {
  value = aws_s3_bucket.app.bucket
}

output "ssh_command" {
  value = "ssh -i ~/.ssh/labsuser.pem ubuntu@${aws_eip.k3s.public_ip}"
}

output "cloudwatch_dashboard_url" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards:name=${var.project}"
}

# Feeds Ansible: terraform output -raw ansible_inventory > ../ansible/inventory.ini
output "ansible_inventory" {
  value = <<-EOT
    [k3s]
    ${aws_eip.k3s.public_ip} ansible_user=ubuntu ansible_ssh_private_key_file=~/.ssh/labsuser.pem

    [k3s:vars]
    s3_bucket=${aws_s3_bucket.app.bucket}
    aws_region=${var.region}
    project=${var.project}
  EOT
}
