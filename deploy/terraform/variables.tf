variable "project" {
  type    = string
  default = "specforge"
}

variable "environment" {
  type    = string
  default = "prod"
}

variable "region" {
  type    = string
  default = "us-east-1" # AWS Academy Learner Lab only allows us-east-1 / us-west-2
}

variable "instance_type" {
  description = "k3s single-node cluster. t3.large (2 vCPU, 8 GiB) is the largest size Learner Lab reliably allows."
  type        = string
  default     = "t3.large"
}

variable "root_volume_gb" {
  type    = number
  default = 30
}

variable "key_name" {
  description = "Existing EC2 key pair. In Learner Lab this is 'vockey' (download labsuser.pem from AWS Details)."
  type        = string
  default     = "vockey"
}

variable "instance_profile" {
  description = "Learner Lab cannot create IAM roles; reuse the pre-made LabInstanceProfile."
  type        = string
  default     = "LabInstanceProfile"
}

variable "admin_cidr" {
  description = "Your public IP in CIDR form for SSH, e.g. 203.0.113.7/32. Find it with: curl -s ifconfig.me"
  type        = string
  validation {
    condition     = can(cidrhost(var.admin_cidr, 0)) && var.admin_cidr != "0.0.0.0/0"
    error_message = "admin_cidr must be a valid CIDR and must not be 0.0.0.0/0."
  }
}

variable "alarm_email" {
  description = "Optional e-mail for CloudWatch alarm notifications (confirm the SNS subscription mail)."
  type        = string
  default     = ""
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}
