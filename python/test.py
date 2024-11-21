import logging
import os
from typing import Dict, List

import boto3
import pandas as pd

aws_region = os.environ.get("AWS_REGION")

# Please note that all metrics' properties, i.e. MetricName and dimensions' names,
# must be in PascalCase. That's to satisfy a tool used by the Periscope team in exporting
# metrics from CloudWatch to Prometheus (ref: https://github.com/ZipRecruiter/cloudwatching/blob/master/pkg/exportcloudwatch/strings.go#L8).


def snake_to_pascal_case(in_str: str) -> str:
    "Converts 'feature_name' to 'FeatureName'"
    return in_str.replace("_", " ").title().replace(" ", "")


def get_metric_dimensions(customer_id: str, customer_name: str, pod: str, lifecycle: str) -> List[Dict]:
    """
    Returns a list of metric dimensions for a given customer_id and pod.
    Used for publishing metrics to Cloudwatch.
    """
    return [
        {"Name": "CustomerId", "Value": customer_id},
        {"Name": "CustomerName", "Value": customer_name},
        {"Name": "Pod", "Value": pod},
        {"Name": "Lifecycle", "Value": lifecycle},
    ]


def publish_cloudwatch_metrics(metrics_data: List[Dict], namespace: str) -> None:
    """
    Publishes metrics to Cloudwatch under specified namespace
    """
    logging.info(f"Sending metrics: {metrics_data}")
    cw_client = boto3.client("cloudwatch", region_name=aws_region)
    cw_client.put_metric_data(MetricData=metrics_data, Namespace=namespace)


def prepare_feature_handling_metrics(
    customer_id: str,
    customer_name: str,
    dropped_identities_count: int,
    all_nan_identities_count: int,
    imputed_values_counts: Dict[str, int],
    pod: str,
) -> List[Dict]:
    """
    Prepares metrics for feature handling
    """

    dimensions = get_metric_dimensions(customer_id, customer_name, pod, "Scoring")

    metric_data = [
        {
            "MetricName": snake_to_pascal_case(feature_name),
            "Dimensions": dimensions,
            "Unit": "Count",
            "Value": int(nan_count),
        }
        for (feature_name, nan_count) in imputed_values_counts.items()
    ]
    metric_data.append(
        {
            "MetricName": "DroppedIdentities",
            "Dimensions": dimensions,
            "Unit": "Count",
            "Value": dropped_identities_count,
        }
    )
    metric_data.append(
        {
            "MetricName": "AllNaNFeaturesIdentities",
            "Dimensions": dimensions,
            "Unit": "Count",
            "Value": all_nan_identities_count,
        }
    )
    return metric_data


def prepare_feature_metrics(customer_id: str, customer_name: str, features: pd.DataFrame, pod: str) -> List[Dict]:
    """
    Prepares metrics for feature handling
    """

    dimensions = get_metric_dimensions(customer_id, customer_name, pod, "Scoring")

    nan_counts = features.isna().sum(axis=0).to_dict()
    return [
        {
            "MetricName": snake_to_pascal_case(feature_name),
            "Dimensions": dimensions,
            "Unit": "Count",
            "Value": int(nan_count),
        }
        for (feature_name, nan_count) in nan_counts.items()
    ]


def prepare_lso_metrics(
    customer_id: str,
    customer_name: str,
    threshold: float,
    outliers_count: int,
    identities_count: int,
    outliers_ratio: float,
    assigned_entitlements_count: int,
    pod: str,
) -> List[Dict]:
    """
    Prepares metrics for LSO
    """

    dimensions = get_metric_dimensions(customer_id, customer_name, pod, "Scoring")

    return [
        {
            "MetricName": "Threshold",
            "Dimensions": dimensions,
            "Unit": "None",
            "Value": float(threshold),
        },
        {
            "MetricName": "OutliersCount",
            "Dimensions": dimensions,
            "Unit": "Count",
            "Value": int(outliers_count),
        },
        {
            "MetricName": "TotalIdentitiesCount",
            "Dimensions": dimensions,
            "Unit": "Count",
            "Value": int(identities_count),
        },
        {
            "MetricName": "OutliersRatio",
            "Dimensions": dimensions,
            "Unit": "None",
            "Value": float(outliers_ratio),
        },
        {
            "MetricName": "TotalAssignedEntitlementsCount",
            "Dimensions": dimensions,
            "Unit": "Count",
            "Value": int(assigned_entitlements_count),
        },
    ]