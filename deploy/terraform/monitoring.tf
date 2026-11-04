locals {
  log_groups = ["api", "worker", "web", "system"]
}

resource "aws_cloudwatch_log_group" "app" {
  for_each          = toset(local.log_groups)
  name              = "/${var.project}/${each.key}"
  retention_in_days = 14
}

resource "aws_sns_topic" "alarms" {
  name = "${var.project}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

# API access log lines look like: "... GET /api/projects 500 12.3ms"
resource "aws_cloudwatch_log_metric_filter" "api_5xx" {
  name           = "${var.project}-api-5xx"
  log_group_name = aws_cloudwatch_log_group.app["api"].name
  pattern        = "%\\s5[0-9][0-9]\\s[0-9.]+ms%"
  metric_transformation {
    name          = "Api5xx"
    namespace     = "SPECForge"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  alarm_name          = "${var.project}-cpu-high"
  alarm_description   = "EC2 CPU above 80% for 10 minutes"
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  dimensions          = { InstanceId = aws_instance.k3s.id }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "status_check" {
  alarm_name          = "${var.project}-status-check-failed"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed"
  dimensions          = { InstanceId = aws_instance.k3s.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${var.project}-api-5xx"
  alarm_description   = "More than 5 API 5xx responses in 5 minutes"
  namespace           = "SPECForge"
  metric_name         = "Api5xx"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "queue_backlog" {
  alarm_name          = "${var.project}-queue-backlog"
  alarm_description   = "Celery queue backlog above 20 jobs for 5 minutes"
  namespace           = "SPECForge"
  metric_name         = "QueueBacklog"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 20
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
}

locals {
  instance_dim = ["InstanceId", aws_instance.k3s.id]
  dashboard_widgets = [
    {
      type = "metric", x = 0, y = 0, width = 12, height = 6
      properties = {
        title   = "EC2 CPU %", region = var.region, stat = "Average", period = 300
        metrics = [concat(["AWS/EC2", "CPUUtilization"], local.instance_dim)]
      }
    },
    {
      type = "metric", x = 12, y = 0, width = 12, height = 6
      properties = {
        title = "Memory & disk used %", region = var.region, stat = "Average", period = 300
        metrics = [
          concat(["CWAgent", "mem_used_percent"], local.instance_dim),
          concat(["CWAgent", "disk_used_percent"], local.instance_dim, ["path", "/"]),
        ]
      }
    },
    {
      type = "metric", x = 0, y = 6, width = 12, height = 6
      properties = {
        title   = "API 5xx responses", region = var.region, stat = "Sum", period = 300
        metrics = [["SPECForge", "Api5xx"]]
      }
    },
    {
      type = "metric", x = 12, y = 6, width = 12, height = 6
      properties = {
        title   = "Celery queue backlog", region = var.region, stat = "Maximum", period = 60
        metrics = [["SPECForge", "QueueBacklog"]]
      }
    },
    {
      type = "log", x = 0, y = 12, width = 24, height = 6
      properties = {
        title = "Recent API errors", region = var.region
        query = "SOURCE '/${var.project}/api' | fields @timestamp, @message | filter @message like /ERROR| 5\\d\\d / | sort @timestamp desc | limit 50"
      }
    },
  ]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = var.project
  dashboard_body = jsonencode({ widgets = local.dashboard_widgets })
}
