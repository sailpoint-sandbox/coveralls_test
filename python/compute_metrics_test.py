""" Quality Metrics Computation."""

import argparse
import json
import os
import tarfile
from collections.abc import Iterable
from typing import Any, Optional

import numpy as np
import pandas as pd

from outliers.metrics.intra_prob_dist import (
    AggregationType,
    CoreType,
    DistanceType,
    compute_intra_distance_metric,
)
from outliers.metrics.neighbor_count_udfs import AggType, compute_neighbor_count_metric
from outliers.utils.error_handler import UnactionableError, persist_error
from outliers.utils.logging import get_logger
from outliers.utils.train_metric_utils import (
    create_report,
    exp_log_model_metrics,
    printable_model_metrics,
    put_model_metrics,
    seed_default_value,
)

customer_id = os.environ.get("CUSTOMER_ID", "unknown")
customer_pod = os.environ.get("POD", "unknown")
region = os.environ.get("AWS_REGION")
logger = get_logger("ModelMetrics", customer_id=customer_id, pod=customer_pod)

# Set Panda's dislay params
pd.set_option("display.max_rows", 10)
pd.set_option("display.max_columns", 20)
pd.set_option("display.width", 1000)


def compute_model_quality_metrics(df: pd.DataFrame, f_names: list[str]) -> Iterable[tuple[str, float]]:
    """Computes model quality metrics

    Arguments:
        df: Dataframe containg all needed features and model computed scores. Only outliers have scores.
        f_names: List of feature names that were used in the model training.

    Returns:
        Iterator of (metric_name, metric_value) for each metric computed.
        In case there are some problems with computing the metric, the value is set to x_BAD_METRIC_VALUE, often 101.

    """
    #### Intra Probability Distance Metric ####
    distance_types = (DistanceType.AbsMean, DistanceType.L2)
    agg_types = (AggregationType.Mean,)
    core_types = (CoreType.Mean,)
    try:
        for m_name, m_value in compute_intra_distance_metric(df, f_names, distance_types, agg_types, core_types):
            yield m_name, round(m_value, 3)
    except Exception as e:
        logger.error(f"Error computing Intra Probability Distance Metric. Exception: {e}")

    #### Neighbor Count Metric ####
    radii = np.arange(0.05, 2.0, 0.15)
    agg_type = AggType.Mean
    try:
        for m_name, m_value in compute_neighbor_count_metric(df, f_names, radii, agg_type=agg_type):
            yield (m_name, round(m_value, 3))
    except Exception as e:
        logger.error(f"Error computing Neighbor Count Metric. Exception: {e}")

    return


def store_metrics_artifacts(output_dir: str, report_dict: dict[str, dict]) -> None:
    logger.info(report_dict)
    evaluation_path = os.path.join(output_dir, "evaluation.json")
    logger.info(f"Writing out quality metrics evaluation report to {evaluation_path}")
    with open(evaluation_path, "w") as f:
        json.dump(report_dict, f)


def compute_metrics(
    model_dir: str,
    exp: Optional[Any] = None,
) -> None:
    """Computes the quality metrics. Currently intra probability distance and neighbor count metric.

    After training and determinig outliers, we compute some descriptive and statistical metrics
    to qualify how good the model performed. These are written both to stdout and a file.

    Arguments:
        model_dir: Path to a directory where the model artifacts are written to.
        exp: Experiment object to log metrics to.
    """
    predictions_file_path = os.path.join(model_dir, "predictions.csv")
    predictions = pd.read_csv(predictions_file_path)

    columns_path = os.path.join(model_dir, "features.json")
    with open(columns_path) as f:
        feature_cols = json.load(f)

    metrics_path = os.path.join(model_dir, "evaluation.json")
    with open(metrics_path) as f:
        metrics = json.load(f)

    qa_metrics = {}
    for metric_name, metric_value in compute_model_quality_metrics(predictions, feature_cols):
        put_model_metrics(logger, metric_name=metric_value)
        qa_metrics[metric_name] = metric_value

    logger.info(printable_model_metrics(**qa_metrics))

    report_dict = create_report(**qa_metrics)
    metrics["evaluation_metrics"].update(report_dict["evaluation_metrics"])

    if exp is not None:
        exp_log_model_metrics(exp, **qa_metrics)

    store_metrics_artifacts(output_dir=model_dir, report_dict=metrics)


def extract_model_artifacts(
    model_dir: str,
) -> None:
    # Extract inputs from training step:
    # ['model.tar.gz', 'predictions.csv', 'features.json', 'evaluation.json', 'model.joblib', 'thresholds.json']
    model_path = os.path.join(model_dir, "model.tar.gz")
    if os.path.exists(model_path):
        model_artifacts_path = os.path.join(model_dir, "artifacts")
        if not os.path.exists(model_artifacts_path):
            os.makedirs(model_artifacts_path, exist_ok=True)
        tar = tarfile.open(model_path)
        tar.extractall(path=model_artifacts_path)
        tar.close()
        return model_artifacts_path
    return model_dir


def main():
    logger.info("Starting Metrics Computation...")
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=str, default=os.environ.get("SM_MODEL_DIR", "/opt/ml/model/"))
    parser.add_argument("--seed", type=int, default=seed_default_value())
    args = parser.parse_args()

    logger.info(f"Received arguments {args}")
    model_dir = extract_model_artifacts(args.model_dir)

    compute_metrics(model_dir)

    logger.info("Done.")


if __name__ == "__main__":
    try:
        main()
    except UnactionableError as ue:
        persist_error(ue)
        logger.exception("Unactionable error. Soft exit. Please see logs for details.")
    except Exception:
        logger.exception("Global error. Please see file logs for details.")
        raise